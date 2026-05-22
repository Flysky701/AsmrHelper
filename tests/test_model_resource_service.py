from __future__ import annotations

from textwrap import dedent

from src.core.resources.model_service import ModelService


def test_install_family_all_expands_family_members_and_required_assets(tmp_path):
    catalog_path = tmp_path / "models.yaml"
    catalog_path.write_text(
        dedent(
            """
            models:
              - id: family-base
                kind: local
                category: asr
                provider: sample
                family_id: sample_family
                display_name: Family Base
                description: Base model
                install_root: models
                install_path: sample/base
                supports_install: true
                install_strategy: huggingface_snapshot
                required_assets: [shared-tokenizer]

              - id: family-large
                kind: local
                category: asr
                provider: sample
                family_id: sample_family
                display_name: Family Large
                description: Large model
                install_root: models
                install_path: sample/large
                supports_install: true
                install_strategy: huggingface_snapshot

              - id: shared-tokenizer
                kind: local
                category: asr
                provider: sample
                family_id: sample_family_assets
                display_name: Shared Tokenizer
                description: Tokenizer asset
                install_root: models
                install_path: sample/tokenizer
                supports_install: true
                install_strategy: huggingface_snapshot
            """
        ).strip(),
        encoding="utf-8",
    )

    service = ModelService(catalog_path=catalog_path)
    installed_ids: list[str] = []

    def fake_install(entry, mirror=None, force=False):
        installed_ids.append(entry.id)
        return True

    service.installer.install_local_model = fake_install

    result = service.install("family-base", install_mode="family_all")

    assert result is True
    assert installed_ids == ["family-base", "shared-tokenizer", "family-large"]
