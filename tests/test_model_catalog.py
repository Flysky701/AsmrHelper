from __future__ import annotations

from textwrap import dedent

import pytest

from src.core.resources.model_catalog import load_catalog_file


def test_load_catalog_file_parses_extended_metadata(tmp_path):
    catalog_path = tmp_path / "models.yaml"
    catalog_path.write_text(
        dedent(
            """
            models:
              - id: sample-model
                kind: local
                category: asr
                provider: sample_provider
                family_id: sample_family
                variant_group: sample_main
                variant_tier: standard
                is_primary_variant: true
                dependency_group: sample_dep_group
                display_name: Sample Model
                description: Sample description
                install_root: models
                install_path: sample/model
                required_files: [model.bin]
                supports_install: true
                supports_remove: true
                install_strategy: huggingface_snapshot
                required_python_extras: [sample_extra]
                required_runtime_packages: [sample-runtime]
                recommended_runtime_packages: [flash-attn]
                required_assets: [sample-tokenizer]
                runtime_profile: transformers_basic
                supported_os: [windows, linux]
                supported_python:
                  min: "3.10"
                  max: "3.13"
                preferred_runtime: python_package_local
                required_system_tools: [ffmpeg]
                install_modes: [single, family_all]
                default_install_mode: single
                auto_install_dependencies: true
                allow_remote_code: true
                download_sources:
                  - type: huggingface
                    repo_id: sample/model
                post_install_checks:
                  - type: file_check
                sample_inference_policy:
                  enabled: false
                healthcheck_timeout_seconds: 90
            """
        ).strip(),
        encoding="utf-8",
    )

    catalog = load_catalog_file(catalog_path)
    entry = catalog.get("sample-model")

    assert entry.family_id == "sample_family"
    assert entry.variant_group == "sample_main"
    assert entry.variant_tier == "standard"
    assert entry.is_primary_variant is True
    assert entry.dependency_group == "sample_dep_group"
    assert entry.required_python_extras == ["sample_extra"]
    assert entry.required_runtime_packages == ["sample-runtime"]
    assert entry.recommended_runtime_packages == ["flash-attn"]
    assert entry.required_assets == ["sample-tokenizer"]
    assert entry.runtime_profile == "transformers_basic"
    assert entry.supported_os == ["windows", "linux"]
    assert entry.supported_python == {"min": "3.10", "max": "3.13"}
    assert entry.preferred_runtime == "python_package_local"
    assert entry.required_system_tools == ["ffmpeg"]
    assert entry.install_modes == ["single", "family_all"]
    assert entry.default_install_mode == "single"
    assert entry.auto_install_dependencies is True
    assert entry.allow_remote_code is True
    assert entry.download_sources == [{"type": "huggingface", "repo_id": "sample/model"}]
    assert entry.post_install_checks == [{"type": "file_check"}]
    assert entry.sample_inference_policy == {"enabled": False}
    assert entry.healthcheck_timeout_seconds == 90


def test_load_catalog_file_rejects_invalid_supported_python_shape(tmp_path):
    catalog_path = tmp_path / "models.yaml"
    catalog_path.write_text(
        dedent(
            """
            models:
              - id: bad-model
                kind: local
                category: asr
                display_name: Bad Model
                description: Invalid supported_python
                install_path: bad/model
                supported_python: "3.10"
            """
        ).strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="supported_python"):
        load_catalog_file(catalog_path)
