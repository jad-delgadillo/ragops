"""Documentation generator that uses LLMs to produce project docs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from services.cli.docgen.analyzer import CodeContext

if TYPE_CHECKING:
    from services.core.providers import LLMProvider

logger = logging.getLogger(__name__)


class DocGenerator:
    """Generates Markdown documentation from project context using LLMs."""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    def generate_readme(self, ctx: CodeContext) -> str:
        """Generate a comprehensive README.md."""
        prompt = self._build_prompt(
            ctx,
            doc_type="README.md",
            focus="Overview, setup, usage instructions, and value proposition.",
        )
        return self.llm_provider.generate(prompt)

    def generate_architecture(self, ctx: CodeContext) -> str:
        """Generate an ARCHITECTURE.md."""
        prompt = self._build_prompt(
            ctx,
            doc_type="ARCHITECTURE.md",
            focus="System design, component relationships, data flow, and technology choices.",
        )
        return self.llm_provider.generate(prompt)

    def generate_api(self, ctx: CodeContext) -> str:
        """Generate an API.md (or CONTRACT.md)."""
        prompt = self._build_prompt(
            ctx,
            doc_type="API.md",
            focus="Detailed API documentation, endpoints, data models, and authentication.",
        )
        return self.llm_provider.generate(prompt)

    def _build_prompt(self, ctx: CodeContext, doc_type: str, focus: str) -> str:
        """Construct a prompt for the LLM based on extracted project context."""
        # Convert context to a formatted string for the prompt
        tree_str = "\n".join(ctx.file_tree[:50])  # Limit tree size
        if len(ctx.file_tree) > 50:
            tree_str += f"\n... and {len(ctx.file_tree) - 50} more files"

        symbols_str = ""
        for file, data in ctx.key_symbols.items():
            symbols_str += f"\n### File: {file}\n"
            if "docstring" in data and data["docstring"]:
                symbols_str += f"Docstring: {data['docstring']}\n"
            if "classes" in data:
                for cls in data["classes"]:
                    symbols_str += f"Class: {cls['name']} (Methods: {', '.join(cls['methods'])})\n"
            if "functions" in data:
                for func in data["functions"]:
                    symbols_str += f"Function: {func['name']}\n"

        return f"""You are a professional Technical Writer and Software Architect.
Your task is to generate {doc_type} for the project '{ctx.project_name}'.

The documentation should focus on: {focus}

Project Context:
- Tech Stack: {', '.join(ctx.tech_stack)}
- File Structure (top 50 files):
{tree_str}

Key Source Code Insight (Classes, Functions, Docstrings):
{symbols_str}

Instructions:
1. Write in clear, professional technical English.
2. Use GitHub Flavored Markdown (GFM).
3. Be specific and derive as much information as possible from
   the file structure and key symbols provided.
4. If the structure suggests a specific framework
   (e.g. Next.js, FastAPI, AWS Lambda), tailor the docs accordingly.
5. Do not hallucinate features not hinted at in the code,
   but you can suggest standard best practices for the detected stack.

Response should be ONLY the Markdown content for the file.
"""
