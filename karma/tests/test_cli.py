import pytest
from click.testing import CliRunner
from karma.cli import cli

def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert "LLM Middleware Runtime" in result.output or "karma" in result.output.lower()

def test_cli_no_args():
    runner = CliRunner()
    result = runner.invoke(cli)
    assert result.exit_code == 0
