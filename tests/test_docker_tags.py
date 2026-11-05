"""Ensure the Docker publish workflow keeps a stable channel separate from main."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci-docker.yml"


def test_stable_and_latest_only_on_version_tags():
    text = WORKFLOW.read_text(encoding="utf-8")
    # latest / stable must be gated on a v* tag, not on the default branch
    assert "type=raw,value=latest,enable=${{ startsWith(github.ref, 'refs/tags/v') }}" in text
    assert "type=raw,value=stable,enable=${{ startsWith(github.ref, 'refs/tags/v') }}" in text
    # Must not re-introduce the old "always on default branch" rule
    assert "type=raw,value=latest,enable={{is_default_branch}}" not in text


def test_main_and_edge_tags_for_testing_channel():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "type=raw,value=main,enable=${{ github.ref == 'refs/heads/main' }}" in text
    assert "type=raw,value=edge,enable=${{ github.ref == 'refs/heads/main' }}" in text


def test_sha_and_semver_tags_still_present():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "type=sha,format=short" in text
    assert "type=semver,pattern={{version}}" in text
    assert "type=semver,pattern={{major}}.{{minor}}" in text
