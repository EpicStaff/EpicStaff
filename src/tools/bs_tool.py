import logging

logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
from rich.console import Console
from rich.syntax import Syntax
from pydantic.v1 import BaseModel, Field
from langchain.tools import tool
from pygments.lexer import RegexLexer
from pygments.token import Token
from typing import Type, Any
from crewai_tools import BaseTool


class BSharpLexer(RegexLexer):
    """
    Custom lexer for the BSharp language, defining syntax highlighting rules using Pygments.
    """

    name = "BSharp"
    aliases = ["bsharp"]
    filenames = ["*.bs"]

    tokens = {
        "root": [
            (r"\bobject\b", Token.Keyword),
            (r"\bprocedure\b", Token.Keyword.Declaration),
            (r"\bif\b", Token.Keyword),
            (r"\berror\b", Token.Keyword),
            (r"[a-zA-Z_][a-zA-Z0-9_]*", Token.Name),
            (r":", Token.Punctuation),
            (r"[{}(),;]", Token.Punctuation),
            (r'".*?"', Token.String),
            (r"\d+", Token.Number),
            (r"#.*$", Token.Comment),
            (r"\s+", Token.Text),
        ]
    }


class BSharpCodeToolSchema(BaseModel):
    """
    Input schema for BSharpCodeTool, specifying the required parameters for code highlighting.
    """

    code: str = Field(..., description="BSharp code to be highlighted and displayed.")


class BSharpCodeTool(BaseTool):
    """
    Tool to display BSharp code with syntax highlighting using the Rich library and a custom Pygments lexer.
    """

    name: str = "BSharp Code Output Tool"
    description: str = (
        "Tool to display BSharp code with syntax highlighting. Takes in one parameter: 'code' - the BSharp code to be highlighted and displayed."
    )
    args_schema: Type[BaseModel] = BSharpCodeToolSchema

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._generate_description()  # Call to the inherited method to set the initial description

    def _run(self, **kwargs: Any) -> Any:
        code = kwargs.get("code")
        if not code:
            return "Error: No code provided for highlighting. Please provide BSharp code as the 'code' parameter."

        console = Console()
        syntax = Syntax(
            code, lexer=BSharpLexer(), theme="github-dark", line_numbers=True
        )
        console.print(syntax)
        return code


# Example usage
if __name__ == "__main__":
    tool = BSharpCodeTool()
    tool.run(
        code="""
    object Person
        id:Integer
        name:String

    procedure AddPerson(PersonDTO, out Integer)
        if People.ContainsKey(PersonDTO.id)
            error[InvalidPersonId] "Person with ID already exists."
    """
    )
