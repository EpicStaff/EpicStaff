import pytest
from pytest_mock import mocker

from custom_tools import CLITool
from tests.tools_tests.fixtures import interpreter_tool


class TestInterpreterTool:

	@pytest.mark.parametrize("command", [
		("print('hello world')"),
		("len(range(10))")
	])
	def test_interpreter_tool(self, mocker, interpreter_tool: CLITool, command):
		""" Test interpreter tool run interpreter.chat command with command"""

		tool = interpreter_tool

		interpreter_mock = mocker.patch('interpreter.interpreter.chat')

		tool._run(command=command)

		interpreter_mock.assert_called_once_with(command)
