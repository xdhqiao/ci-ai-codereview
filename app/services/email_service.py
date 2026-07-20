from __future__ import annotations

import logging
from pathlib import Path
from string import Template
from typing import Mapping, Sequence

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


class EmailServer:
    """Mock email gateway with the same boundary a real provider can implement later."""

    def __init__(
        self,
        settings: Settings | None = None,
        template_root: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sender = self.settings.email_sender
        self.template_root = template_root or Path(__file__).resolve().parent.parent / "templates"

    def send(
        self,
        subject: str,
        email_template: str,
        parameters: Mapping[str, object],
        receivers: Sequence[str],
    ) -> str:
        normalized_receivers = tuple(
            dict.fromkeys(receiver.strip() for receiver in receivers if receiver and receiver.strip())
        )
        if not normalized_receivers:
            logger.info("Mock email skipped: subject=%s reason=no receivers", subject)
            return ""

        rendered_html = self.render(email_template, parameters)
        logger.info(
            "Mock email sent: sender=%s receivers=%s subject=%s template=%s parameter_keys=%s html_length=%s",
            self.sender,
            ",".join(normalized_receivers),
            subject,
            email_template,
            ",".join(sorted(parameters)),
            len(rendered_html),
        )
        return rendered_html

    def render(self, email_template: str, parameters: Mapping[str, object]) -> str:
        template_source = self._template_source(email_template)
        string_parameters = {key: str(value) for key, value in parameters.items()}
        return Template(template_source).substitute(string_parameters)

    def _template_source(self, email_template: str) -> str:
        if "<html" in email_template.lower() or "<!doctype" in email_template.lower():
            return email_template
        template_path = (self.template_root / email_template).resolve()
        template_root = self.template_root.resolve()
        if template_path != template_root and template_root not in template_path.parents:
            raise ValueError("email template must stay inside the template directory")
        return template_path.read_text(encoding="utf-8")
