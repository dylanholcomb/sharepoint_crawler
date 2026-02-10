"""
AI-powered document classification using Azure OpenAI.

Takes extracted text content and generates:
- Document category/topic
- Brief summary
- Keywords
- Confidence score
- Suggested folder path
"""

import json
import logging
import time

from openai import AzureOpenAI

logger = logging.getLogger(__name__)


CLASSIFICATION_PROMPT = """You are a document classification assistant for a government/enterprise SharePoint reorganization project.

Analyze the following document and return a JSON object with these fields:

- "category": The primary document category. Choose from or create categories like:
  HR, Finance, Legal, IT, Operations, Marketing, Sales, Compliance,
  Project Management, RFP/RFI, Policy, Training, Meeting Notes,
  Templates, Reports, Contracts, Correspondence, Technical Documentation,
  Strategic Planning, or suggest a more specific one if appropriate.

- "subcategory": A more specific subcategory within the main category.
  For example: "Finance > Budget Reports" or "HR > Onboarding".

- "summary": A 1-2 sentence summary of what this document is about.

- "keywords": A list of 3-7 relevant keywords.

- "confidence": Your confidence in this classification from 0.0 to 1.0.

- "suggested_folder": A suggested folder path for this document using a
  clean hierarchy. Use forward slashes. Example: "Finance/Budget Reports/FY2024"
  or "RFP Responses/CDPH/CalSYS". Keep it 2-4 levels deep.

- "sensitivity_flag": One of "public", "internal", "confidential", or "review_needed".
  Flag as "review_needed" if the document appears to contain PII, financial data,
  legal agreements, or anything that should be reviewed before reorganizing.

Return ONLY valid JSON, no other text."""


class DocumentClassifier:
    """Classifies documents using Azure OpenAI."""

    # Rate limiting for Azure OpenAI
    REQUEST_DELAY = 0.5  # seconds between requests

    def __init__(self, api_key: str, endpoint: str,
                 deployment: str = "gpt-4o", api_version: str = "2024-10-21"):
        """Initialize the classifier with Azure OpenAI credentials.

        Args:
            api_key: Azure OpenAI API key.
            endpoint: Azure OpenAI endpoint URL.
            deployment: Model deployment name (default: gpt-4o).
            api_version: Azure OpenAI API version.
        """
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        self.deployment = deployment
        self.stats = {
            "classified": 0,
            "skipped_no_content": 0,
            "errors": 0,
        }

    def classify(self, text: str, file_name: str,
                 current_path: str) -> dict:
        """Classify a document based on its extracted text.

        Args:
            text: Extracted text content from the document.
            file_name: Original filename (provides context).
            current_path: Current folder path in SharePoint.

        Returns:
            Classification dict with category, summary, keywords, etc.
            Returns a default dict if classification fails.
        """
        if not text or len(text.strip()) < 20:
            self.stats["skipped_no_content"] += 1
            return self._default_classification(
                "Insufficient content for classification"
            )

        # Truncate text for the prompt to control token usage
        truncated = text[:4000]

        user_message = (
            f"Filename: {file_name}\n"
            f"Current location: {current_path}\n\n"
            f"Document content:\n{truncated}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": CLASSIFICATION_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"},
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)

            # Validate expected fields
            required_fields = [
                "category", "subcategory", "summary",
                "keywords", "confidence", "suggested_folder",
            ]
            for field in required_fields:
                if field not in result:
                    result[field] = "Unknown" if field != "keywords" else []

            if "sensitivity_flag" not in result:
                result["sensitivity_flag"] = "review_needed"

            self.stats["classified"] += 1
            logger.debug(
                f"Classified {file_name}: "
                f"{result['category']} ({result['confidence']})"
            )

            time.sleep(self.REQUEST_DELAY)
            return result

        except json.JSONDecodeError as e:
            logger.warning(
                f"JSON parse error for {file_name}: {e}"
            )
            self.stats["errors"] += 1
            return self._default_classification("AI response was not valid JSON")

        except Exception as e:
            logger.warning(f"Classification failed for {file_name}: {e}")
            self.stats["errors"] += 1
            return self._default_classification(str(e))

    def classify_batch(self, documents: list) -> list:
        """Classify a batch of documents.

        Args:
            documents: List of dicts, each with at least:
                - file_name
                - full_path
                - extracted_text (from the extractor)

        Returns:
            The same list with classification fields added to each doc.
        """
        total = len(documents)
        logger.info(f"Classifying {total} documents...")

        for i, doc in enumerate(documents):
            text = doc.get("extracted_text", "")
            file_name = doc.get("file_name", "Unknown")
            current_path = doc.get("full_path", "")

            if i % 10 == 0:
                logger.info(f"  Progress: {i}/{total} documents classified")

            classification = self.classify(text, file_name, current_path)

            # Merge classification into the document record
            doc["ai_category"] = classification.get("category", "")
            doc["ai_subcategory"] = classification.get("subcategory", "")
            doc["ai_summary"] = classification.get("summary", "")
            doc["ai_keywords"] = ", ".join(
                classification.get("keywords", [])
            )
            doc["ai_confidence"] = classification.get("confidence", 0)
            doc["ai_suggested_folder"] = classification.get(
                "suggested_folder", ""
            )
            doc["ai_sensitivity_flag"] = classification.get(
                "sensitivity_flag", "review_needed"
            )

        logger.info(f"Classification complete:")
        logger.info(f"  Classified:          {self.stats['classified']}")
        logger.info(f"  Skipped (no content): {self.stats['skipped_no_content']}")
        logger.info(f"  Errors:              {self.stats['errors']}")

        return documents

    @staticmethod
    def _default_classification(reason: str) -> dict:
        """Return a default classification when AI can't classify."""
        return {
            "category": "Unclassified",
            "subcategory": "Unclassified",
            "summary": reason,
            "keywords": [],
            "confidence": 0.0,
            "suggested_folder": "Unclassified/Review Needed",
            "sensitivity_flag": "review_needed",
        }
