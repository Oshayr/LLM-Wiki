"""
RAG handler for wiki chat — augments chat messages with wiki context.

When RAG mode is enabled, user messages are preprocessed:
1. Run TF-IDF full-text search against the wiki pages
2. Retrieve top-k section chunks as context
3. Format the augmented prompt with citation instructions
4. Post-process response to verify citations are grounded
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class RAGHandler:
    """Augments chat messages with wiki context for cited responses."""

    def __init__(self, wiki_dir: str):
        self.wiki_dir = Path(wiki_dir)
        self.pages_dir = self.wiki_dir / "pages"
        self.bin_dir = Path(__file__).parent.parent.parent.parent / "bin"
        self.enabled = True
        self.token_budget = 4000

    def augment_message(self, user_message: str, page_context: str = None) -> str:
        """Augment a user message with RAG context from the wiki.

        Args:
            user_message: The user's chat message
            page_context: Optional slug of the page being viewed

        Returns:
            Augmented prompt with wiki context and citation instructions
        """
        if not self.enabled:
            return user_message

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.bin_dir / "rag.py"),
                    "query",
                    str(self.pages_dir),
                    user_message,
                    "--budget",
                    str(self.token_budget),
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning(f"RAG query failed: {result.stderr[:200]}")
                return user_message

            # The --json flag outputs the formatted prompt directly
            augmented = result.stdout.strip()
            if augmented and len(augmented) > len(user_message):
                return augmented

        except subprocess.TimeoutExpired:
            logger.warning("RAG query timed out", exc_info=True)
        except Exception as e:
            logger.warning(f"RAG augmentation error: {e}", exc_info=True)

        return user_message

    def verify_citations(self, response: str, context_slugs: set[str]) -> list[dict]:
        """Check that citations in the response are grounded in provided context.

        Returns list of issues found.
        """
        import re

        citations = re.findall(r"\[\[([^\]]+)\]\]", response)
        issues = []

        for cite in citations:
            slug = cite.split("#")[0].strip()
            if slug not in context_slugs:
                issues.append({
                    "citation": cite,
                    "issue": "ungrounded",
                    "message": f"Citation [[{cite}]] was not in the provided context",
                })

        return issues

    def toggle(self, enabled: bool = None) -> bool:
        """Toggle RAG mode on/off."""
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = not self.enabled
        return self.enabled
