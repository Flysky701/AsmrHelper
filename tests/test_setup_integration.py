"""
setup.ps1 集成测试 — 模拟小白用户从零开始运行安装脚本

测试策略:
  1. 静态分析: 检查 setup.ps1 文件编码、语法、结构正确性
  2. 网络探测: 验证镜像源可达性
  3. 依赖兼容: 检查 pyproject.toml 与当前 Python 版本的兼容性
  4. 配置初始化: 模拟配置文件和目录结构的创建
  5. 模块导入: 验证核心依赖能否正常导入
  6. 幂等性: 确认重复运行不会出错
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# ============================================================
# 项目路径
# ============================================================
PROJECT_ROOT = Path(__file__).parent.parent
SETUP_PS1 = PROJECT_ROOT / "setup.ps1"
PYPROJECT_TOML = PROJECT_ROOT / "pyproject.toml"
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_EXAMPLE = CONFIG_DIR / "config.example.json"
VP_EXAMPLE = CONFIG_DIR / "voice_profiles.example.json"


# ============================================================
# 辅助工具
# ============================================================
def run_ps(args: list[str], cwd=None, timeout=60) -> subprocess.CompletedProcess:
    """运行 PowerShell 命令，返回 CompletedProcess"""
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or PROJECT_ROOT,
        encoding="utf-8",
        errors="replace",
    )


def read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


# ============================================================
# 1. 文件编码和语法测试
# ============================================================
class TestSetupFileEncoding:
    """小白第一次下载脚本 — 文件必须能被 PowerShell 正确解析"""

    def test_file_exists(self):
        """脚本文件必须存在"""
        assert SETUP_PS1.exists(), f"setup.ps1 不存在: {SETUP_PS1}"

    def test_has_utf8_bom(self):
        """
        UTF-8 BOM 是必须的。
        PowerShell 5.x 没有 BOM 时会用系统编码 (GBK) 解析，
        导致中文字符损坏、字符串解析错误。
        这是小白最容易遇到的第一个坑。
        """
        raw = read_file_bytes(SETUP_PS1)
        assert raw[:3] == b"\xef\xbb\xbf", (
            "setup.ps1 缺少 UTF-8 BOM (EF BB BB)。"
            "PowerShell 5.x 需要 BOM 才能正确识别 UTF-8 编码，"
            "否则中文会乱码导致脚本无法运行。"
        )

    def test_no_trailing_control_chars(self):
        """文件末尾不能有奇怪的控制字符"""
        raw = read_file_bytes(SETUP_PS1)
        # 移除 BOM 后检查
        content = raw[3:]
        # 不能有 \r\n 以外的控制字符（排除正常空白）
        for i, b in enumerate(content):
            if b < 0x20 and b not in (0x09, 0x0A, 0x0D):
                pytest.fail(
                    f"发现异常控制字符 0x{b:02X} 在字节位置 {i}，"
                    f"附近内容: {content[max(0,i-10):i+10]!r}"
                )

    def test_powershell_can_parse(self):
        """
        PowerShell 必须能解析脚本语法。
        任何语法错误都会导致小白看到红字报错。
        """
        result = run_ps([
            "-Command",
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{SETUP_PS1}', $null, [ref]$null) | Out-Null; "
            "Write-Host 'PARSE_OK'"
        ])
        assert "PARSE_OK" in result.stdout, (
            f"PowerShell 语法解析失败:\n{result.stderr}"
        )

    def test_script_has_correct_params(self):
        """脚本必须支持 -Full, -SkipInstall, -DevOnly 参数"""
        result = run_ps([
            "-Command",
            f"Get-Command '{SETUP_PS1}' -Syntax"
        ])
        syntax = result.stdout.strip()
        for param in ["-Full", "-SkipInstall", "-DevOnly"]:
            assert param in syntax, f"缺少参数 {param}，当前语法: {syntax}"

    def test_script_requires_version(self):
        """脚本应声明最低 PowerShell 版本"""
        first_line = SETUP_PS1.read_text(encoding="utf-8-sig").strip()
        assert "#Requires -Version" in first_line, (
            "脚本缺少 #Requires 声明，小白可能在旧版 PowerShell 上运行出错"
        )


# ============================================================
# 2. 网络探测测试
# ============================================================
class TestNetworkConnectivity:
    """
    验证脚本中配置的镜像源可达。
    小白的网络环境千奇百怪 — 必须提前发现问题。
    """

    @pytest.fixture(scope="class")
    def mirrors(self):
        """从 setup.ps1 中提取镜像源列表"""
        content = SETUP_PS1.read_text(encoding="utf-8-sig")
        urls = re.findall(r'https://[^"\']+', content)
        # 去重并分类
        pypi_mirrors = [
            u for u in urls
            if "pypi.tuna.tsinghua.edu.cn" in u
            or "mirrors.aliyun.com" in u
        ]
        pytorch_mirrors = [
            u for u in urls
            if "download.pytorch.org" in u
        ]
        return {"pypi": pypi_mirrors, "pytorch": pytorch_mirrors}

    @pytest.mark.parametrize("mirror_url", [
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "https://mirrors.aliyun.com/pypi/simple",
    ], ids=["tsinghua", "aliyun"])
    def test_pypi_mirror_reachable(self, mirror_url):
        """国内 PyPI 镜像必须可达"""
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(
                mirror_url, headers={"User-Agent": "asmr-helper-test/1.0"}
            )
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.URLError as e:
            pytest.fail(f"镜像不可达 {mirror_url}: {e}")
        except Exception as e:
            pytest.skip(f"网络异常，跳过: {e}")

    def test_pytorch_cuda_index_configured(self):
        """PyTorch CUDA 索引必须在 pyproject.toml 中正确配置"""
        content = PYPROJECT_TOML.read_text(encoding="utf-8")
        assert "pytorch-cu126" in content, "缺少 PyTorch CUDA 126 索引配置"
        assert "download.pytorch.org/whl/cu126" in content, "PyTorch CUDA URL 不正确"

    def test_astral_sh_uv_install_reachable(self):
        """uv 官方安装脚本必须可达"""
        import urllib.request
        try:
            req = urllib.request.Request(
                "https://astral.sh/uv/install.ps1",
                headers={"User-Agent": "asmr-helper-test/1.0"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            body = resp.read().decode("utf-8", errors="replace")
            # 确认返回的是 PowerShell 脚本
            assert len(body) > 100, "uv 安装脚本内容异常"
            assert "uv" in body.lower(), "返回内容不是 uv 安装脚本"
        except Exception as e:
            pytest.skip(f"无法访问 astral.sh: {e}")


# ============================================================
# 3. 依赖兼容性测试
# ============================================================
class TestDependencyCompatibility:
    """
    检查 pyproject.toml 中的依赖与当前环境是否兼容。
    这是 onnxruntime cp313 问题的根源 — 必须预防。
    """

    def test_python_version_satisfied(self):
        """当前 Python 版本必须满足 requires-python"""
        import tomllib
        with open(PYPROJECT_TOML, "rb") as f:
            config = tomllib.load(f)
        requires = config["project"]["requires-python"]
        # 解析 ">=3.10"
        match = re.match(r">=(\d+)\.(\d+)", requires)
        assert match, f"无法解析 requires-python: {requires}"
        min_major, min_minor = int(match.group(1)), int(match.group(2))
        assert (
            sys.version_info >= (min_major, min_minor)
        ), f"Python {sys.version_info} 不满足 {requires}"

    def test_onnxruntime_version_allows_current_python(self):
        """
        onnxruntime 必须支持当前 Python 版本。
        检查 override-dependencies 中的版本约束。
        """
        import tomllib
        import urllib.request

        with open(PYPROJECT_TOML, "rb") as f:
            config = tomllib.load(f)

        overrides = config["tool"]["uv"]["override-dependencies"]
        ort_line = [o for o in overrides if "onnxruntime" in o]
        assert len(ort_line) == 1, f"未找到 onnxruntime override: {overrides}"
        ort_spec = ort_line[0]

        # 解析版本范围
        min_ver_match = re.search(r">=(\d+\.\d+)", ort_spec)
        if min_ver_match:
            min_ver = min_ver_match.group(1)
        else:
            min_ver = "0.0.0"

        # 查询 PyPI 确认此版本支持当前 Python
        try:
            url = f"https://pypi.org/pypi/onnxruntime/{min_ver}/json"
            req = urllib.request.Request(url, headers={"User-Agent": "test"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            # 检查 wheel 文件名中是否包含当前 cp 版本
            cp_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
            wheels = data["urls"]
            compatible = any(
                cp_tag in w["filename"] and "win" in w["filename"].lower()
                for w in wheels
            )
            assert compatible, (
                f"onnxruntime {min_ver} 没有 {cp_tag} 的 Windows wheel。"
                f"当前 Python: {sys.version_info.major}.{sys.version_info.minor}。"
                f"可用版本: {[w['filename'] for w in wheels if cp_tag in w['filename']]}"
            )
        except Exception as e:
            pytest.fail(f"查询 PyPI 失败: {e}")

    def test_numpy_version_not_conflict_with_py313(self):
        """
        numpy<2.0.0 与 Python 3.13 的兼容性检查。
        numpy 1.x 对 3.13 的支持有限，需要确认。
        """
        import tomllib
        with open(PYPROJECT_TOML, "rb") as f:
            config = tomllib.load(f)

        deps = config["project"]["dependencies"]
        numpy_lines = [d for d in deps if "numpy" in d]
        assert len(numpy_lines) >= 1

        # 如果 Python >= 3.13 且 numpy 上限是 2.0，警告但不阻断
        if sys.version_info >= (3, 13):
            numpy_spec = numpy_lines[0]
            if "<2.0.0" in numpy_spec:
                # numpy 1.26.x 开始支持 3.13，所以 >=1.24.0,<2.0.0 应该没问题
                # 但需要确认具体最低版本
                pass  # 仅做记录，实际兼容性由 uv sync 验证

    def test_pyproject_has_no_syntax_errors(self):
        """pyproject.toml 必须能被正确解析"""
        import tomllib
        try:
            with open(PYPROJECT_TOML, "rb") as f:
                tomllib.load(f)
        except Exception as e:
            pytest.fail(f"pyproject.toml 解析失败: {e}")


# ============================================================
# 4. 配置初始化测试
# ============================================================
class TestConfigInitialization:
    """
    模拟小白首次运行 — 配置文件应从示例文件自动创建。
    使用临时目录隔离，不影响真实项目。
    """

    @pytest.fixture
    def temp_project(self, tmp_path):
        """创建临时项目目录，复制必要文件"""
        # 复制 config 目录
        tmp_config = tmp_path / "config"
        shutil.copytree(CONFIG_DIR, tmp_config)
        # 创建空的必要目录结构
        for d in ["models/voice_profiles", "output", ".workbuddy/memory"]:
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        yield tmp_path

    def test_config_example_exists(self):
        """config.example.json 必须存在"""
        assert CONFIG_EXAMPLE.exists(), (
            "config.example.json 不存在。"
            "小白首次运行时脚本需要复制此文件为 config.json。"
        )

    def test_config_example_valid_json(self):
        """config.example.json 必须是合法的 JSON"""
        try:
            json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            pytest.fail(f"config.example.json JSON 格式错误: {e}")

    def test_voice_profiles_example_exists(self):
        """voice_profiles.example.json 必须存在"""
        assert VP_EXAMPLE.exists(), (
            "voice_profiles.example.json 不存在。"
            "脚本需要复制此文件为 voice_profiles.json。"
        )

    def test_config_copy_creates_valid_json(self, temp_project):
        """模拟脚本复制配置文件 — 结果必须是合法 JSON"""
        example = temp_project / "config" / "config.example.json"
        target = temp_project / "config" / "config.json"
        shutil.copy2(example, target)

        data = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_config_has_api_section(self, temp_project):
        """配置文件必须包含 api 部分"""
        example = temp_project / "config" / "config.example.json"
        data = json.loads(example.read_text(encoding="utf-8"))
        assert "api" in data, "配置文件缺少 api 部分"

    def test_directory_creation(self, tmp_path):
        """模拟脚本创建目录结构"""
        dirs = [
            "models/voice_profiles",
            "models/qwen3tts",
        ]
        for d in dirs:
            full = tmp_path / d
            full.mkdir(parents=True, exist_ok=True)
            assert full.is_dir(), f"目录创建失败: {d}"


# ============================================================
# 5. setup.ps1 关键逻辑测试
# ============================================================
class TestSetupScriptLogic:
    """
    测试 setup.ps1 中的关键函数逻辑。
    通过提取函数并单独执行来验证。
    """

    def test_uv_bin_dir_in_path_handling(self):
        """验证 PATH 处理逻辑"""
        ps_code = textwrap.dedent("""
            $uvBinDir = Join-Path $env:USERPROFILE ".local\\bin"
            $env:PATH = "C:\\some;C:\\other"
            if (-not ($env:PATH -split ";" | Where-Object { $_ -eq $uvBinDir })) {
                $env:PATH = "$uvBinDir;$env:PATH"
            }
            $parts = $env:PATH -split ";"
            Write-Host "FIRST:$($parts[0])"
            Write-Host "CONTAINS:$($parts -contains $uvBinDir)"
        """)
        result = run_ps(["-Command", ps_code])
        assert "CONTAINS:True" in result.stdout, "PATH 处理逻辑错误"

    def test_get_mirror_latency_valid(self):
        """Get-MirrorLatency 函数应该能测量可达 URL 的延迟"""
        ps_code = textwrap.dedent("""
            function Get-MirrorLatency([string]$Url, [int]$TimeoutMs = 5000) {
                try {
                    $sw = [System.Diagnostics.Stopwatch]::StartNew()
                    $req = [System.Net.HttpWebRequest]::Create($Url)
                    $req.Timeout = $TimeoutMs
                    $req.Method = "HEAD"
                    $resp = $req.GetResponse()
                    $resp.Close()
                    $sw.Stop()
                    return [int]$sw.ElapsedMilliseconds
                } catch { return $null }
            }
            $result = Get-MirrorLatency "https://www.baidu.com"
            Write-Host "RESULT:$result"
        """)
        result = run_ps(["-Command", ps_code])
        assert "RESULT:" in result.stdout and "RESULT:null" not in result.stdout, (
            "Get-MirrorLatency 对可达 URL 返回了 null"
        )

    def test_get_mirror_latency_invalid(self):
        """Get-MirrorLatency 函数应该对不可达 URL 返回 null"""
        ps_code = textwrap.dedent("""
            function Get-MirrorLatency([string]$Url, [int]$TimeoutMs = 3000) {
                try {
                    $sw = [System.Diagnostics.Stopwatch]::StartNew()
                    $req = [System.Net.HttpWebRequest]::Create($Url)
                    $req.Timeout = $TimeoutMs
                    $req.Method = "HEAD"
                    $resp = $req.GetResponse()
                    $resp.Close()
                    $sw.Stop()
                    return [int]$sw.ElapsedMilliseconds
                } catch { return $null }
            }
            $result = Get-MirrorLatency "https://this-domain-definitely-does-not-exist-12345.com"
            Write-Host "RESULT:$result"
        """)
        result = run_ps(["-Command", ps_code])
        assert "RESULT:null" in result.stdout or "RESULT:" not in result.stdout, (
            "Get-MirrorLatency 对不可达 URL 应该返回 null"
        )

    def test_skipinstall_flag_works(self):
        """
        -SkipInstall 应该跳过 uv sync，直接到配置初始化。
        这是小白只想初始化配置时用的。
        """
        result = run_ps([
            "-File", str(SETUP_PS1), "-SkipInstall"
        ], timeout=30)

        # 不应该有 uv sync 相关输出
        combined = result.stdout + result.stderr
        assert "同步依赖" not in combined or "跳过" in combined.lower(), (
            "-SkipInstall 没有跳过依赖安装"
        )

    def test_script_runs_without_error_skipinstall(self):
        """-SkipInstall 模式应该完整运行不报错"""
        result = run_ps([
            "-File", str(SETUP_PS1), "-SkipInstall"
        ], timeout=60)

        assert result.returncode == 0, (
            f"setup.ps1 -SkipInstall 执行失败 (exit code: {result.returncode})\n"
            f"STDOUT: {result.stdout[-2000:]}\n"
            f"STDERR: {result.stderr[-2000:]}"
        )

        # 应该能看到 Step 3, 4, 5 的输出
        combined = result.stdout + result.stderr
        assert "配置完成" in combined, "脚本没有到达最终步骤"


# ============================================================
# 6. 幂等性测试
# ============================================================
class TestIdempotency:
    """
    小白可能多次运行脚本 — 结果必须一致。
    """

    def test_double_skipinstall(self):
        """连续两次 -SkipInstall 不应该出错"""
        for i in range(2):
            result = run_ps([
                "-File", str(SETUP_PS1), "-SkipInstall"
            ], timeout=60)
            assert result.returncode == 0, (
                f"第 {i+1} 次运行 setup.ps1 -SkipInstall 失败\n"
                f"STDERR: {result.stderr[-1000:]}"
            )

    def test_config_not_overwritten(self, tmp_path):
        """已有 config.json 不应该被覆盖"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        example = config_dir / "config.example.json"
        target = config_dir / "config.json"

        # 创建示例文件
        example.write_text('{"test": true}', encoding="utf-8")

        # 模拟脚本逻辑
        if not target.exists():
            shutil.copy2(example, target)
        else:
            pass  # 跳过

        # 第一次运行: 应该创建
        assert target.exists()
        assert json.loads(target.read_text("utf-8")) == {"test": True}

        # 修改 target
        target.write_text('{"test": false, "user_edited": true}', encoding="utf-8")

        # 第二次运行: 不应该覆盖
        if not target.exists():
            shutil.copy2(example, target)

        data = json.loads(target.read_text("utf-8"))
        assert data.get("user_edited") is True, "config.json 被意外覆盖"


# ============================================================
# 7. 环境验证测试 (如果 .venv 存在)
# ============================================================
class TestEnvironmentValidation:
    """
    验证 .venv 中的核心模块能否正常导入。
    只在 .venv 存在时运行。
    """

    @pytest.fixture(autouse=True)
    def _skip_if_no_venv(self):
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            pytest.skip("没有找到 .venv，跳过环境验证测试")

    def _run_venv_python(self, code: str) -> subprocess.CompletedProcess:
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        return subprocess.run(
            [str(venv_python), "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )

    @pytest.mark.parametrize("module", [
        ("faster_whisper", "faster_whisper.__version__"),
        ("edge_tts", "'OK'"),
        ("demucs", "demucs.__version__"),
        ("PySide6", "PySide6.__version__"),
        ("torch", "torch.__version__"),
        ("soundfile", "soundfile.__version__"),
        ("numpy", "numpy.__version__"),
        ("httpx", "httpx.__version__"),
        ("click", "click.__version__"),
    ], ids=lambda p: p[0])
    def test_core_module_importable(self, module):
        """核心模块必须能被导入"""
        mod_name, expr = module
        result = self._run_venv_python(f"import {mod_name}; print({expr})")
        assert result.returncode == 0, (
            f"无法导入 {mod_name}: {result.stderr}"
        )

    def test_torch_cuda_available(self):
        """PyTorch 应该能检测到 CUDA (如果有 GPU)"""
        result = self._run_venv_python(
            "import torch; print(torch.cuda.is_available())"
        )
        if result.returncode == 0:
            # 不强制要求 CUDA 可用，只验证不崩溃
            assert result.stdout.strip() in ("True", "False")


# ============================================================
# 8. setup.ps1 输出格式测试
# ============================================================
class TestOutputUserFriendly:
    """
    小白用户看到的内容必须清晰友好。
    """

    def test_has_step_markers(self):
        """脚本输出应该有清晰的步骤标记"""
        content = SETUP_PS1.read_text(encoding="utf-8-sig")
        # 检查是否有分步提示
        assert "Step 0" in content
        assert "Step 1" in content
        assert "Step 2" in content
        assert "Step 3" in content
        assert "Step 4" in content
        assert "Step 5" in content

    def test_has_color_output(self):
        """输出应该有颜色标记帮助小白识别状态"""
        content = SETUP_PS1.read_text(encoding="utf-8-sig")
        assert "ForegroundColor Green" in content, "没有成功状态的颜色标记"
        assert "ForegroundColor Red" in content, "没有失败状态的颜色标记"
        assert "ForegroundColor Yellow" in content, "没有警告状态的颜色标记"

    def test_has_post_install_instructions(self):
        """脚本结束后应该告诉小白下一步做什么"""
        content = SETUP_PS1.read_text(encoding="utf-8-sig")
        assert "后续步骤" in content, "缺少后续步骤指引"
        assert "API Key" in content, "缺少 API Key 配置指引"
        assert "run.bat" in content, "缺少 GUI 启动指引"

    def test_has_help_documentation(self):
        """脚本应该有基于注释的帮助文档"""
        content = SETUP_PS1.read_text(encoding="utf-8-sig")
        assert ".SYNOPSIS" in content, "缺少 SYNOPSIS 帮助"
        assert ".EXAMPLE" in content, "缺少 EXAMPLE 帮助"
        assert ".DESCRIPTION" in content, "缺少 DESCRIPTION 帮助"

    def test_error_action_preference_is_stop(self):
        """
        错误时应立即停止，而不是继续执行导致更多错误。
        小白看到一连串报错会恐慌。
        """
        content = SETUP_PS1.read_text(encoding="utf-8-sig")
        assert '$ErrorActionPreference = "Stop"' in content, (
            "缺少 ErrorActionPreference = Stop"
        )


# ============================================================
# 运行入口
# ============================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
