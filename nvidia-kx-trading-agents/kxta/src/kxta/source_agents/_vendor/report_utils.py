# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Vendored into the KXTA source-agents layer from the KX "agentic-anomaly-market-research" project
# (faithful copy; imports rewritten and heavy imports made lazy -- no logic changes).
"""
Utility functions for standardizing research agent output formats.

All research agents should return structured output with:
- research_report: Full markdown report
- key_findings: List of 3-5 bullet points
- data_summary: Agent-specific structured data
- sources: List of sources used
- status: "success" | "error" | "no_data"
"""

import re
from typing import List, Dict, Any, Optional


def extract_key_findings_from_markdown(markdown: str,
                                       max_items: int = 5,
                                       section_headers: Optional[List[str]] = None) -> List[str]:
    """
    Extract key findings from a markdown report.

    Looks for sections like "KEY FINDINGS", "Key Findings", "Summary", etc.
    and extracts bullet points from them.

    Args:
        markdown: The markdown text to extract from
        max_items: Maximum number of findings to return
        section_headers: Optional list of section headers to look for

    Returns:
        List of key finding strings (without bullet markers)
    """
    if not markdown:
        return []

    # Default section headers to search for
    if section_headers is None:
        section_headers = [
            "KEY FINDINGS",
            "Key Findings",
            "EXECUTIVE SUMMARY",
            "Executive Summary",
            "Summary",
            "SUMMARY",
            "Main Findings",
            "MAIN FINDINGS",
            "Highlights",
            "HIGHLIGHTS",
        ]

    findings = []

    # Try to find a key findings section
    for header in section_headers:
        # Match header with various markdown formats (##, ###, **bold**, etc.)
        patterns = [
            rf"#+\s*{re.escape(header)}\s*\n(.*?)(?=\n#+\s|\n\*\*[A-Z]|\Z)",
            rf"\*\*{re.escape(header)}\*\*\s*\n(.*?)(?=\n\*\*[A-Z]|\n#+\s|\Z)",
            rf"{re.escape(header)}:\s*\n(.*?)(?=\n[A-Z][A-Za-z\s]+:|\n#+\s|\Z)",
        ]

        for pattern in patterns:
            match = re.search(pattern, markdown, re.IGNORECASE | re.DOTALL)
            if match:
                section_content = match.group(1)
                # Extract bullet points
                bullets = extract_bullets(section_content)
                if bullets:
                    findings.extend(bullets)
                    break

        if findings:
            break

    # If no section found, try to extract any bullet points from the beginning
    if not findings:
        # Look for bullet points anywhere
        findings = extract_bullets(markdown)

    # Deduplicate while preserving order
    seen = set()
    unique_findings = []
    for f in findings:
        f_normalized = f.strip().lower()
        if f_normalized not in seen and len(f.strip()) > 10:
            seen.add(f_normalized)
            unique_findings.append(f.strip())

    return unique_findings[:max_items]


def extract_bullets(text: str) -> List[str]:
    """Extract bullet points from text, including multi-line continuation.

    Handles both bulleted formats (-, *, •, numbered) and plain-text formats
    where the LLM produces lines without bullet markers.
    """
    bullets = []
    lines = text.split('\n')
    current_bullet = None
    bullet_indent = None

    for line in lines:
        # Check if line starts a new bullet point
        bullet_match = re.match(r'^([\s]*)[-*•]\s+(.+)', line)
        numbered_match = re.match(r'^([\s]*)\d+[.)]\s+(.+)', line) if not bullet_match else None
        match = bullet_match or numbered_match

        if match:
            # Save previous bullet if any
            if current_bullet:
                cleaned = _clean_bullet(current_bullet)
                if cleaned and len(cleaned) > 5:
                    bullets.append(cleaned)
            # Start new bullet
            bullet_indent = len(match.group(1))
            current_bullet = match.group(2)
        elif current_bullet is not None and line.strip():
            # Continuation line: non-empty, indented further than bullet start
            line_indent = len(line) - len(line.lstrip())
            if line_indent > bullet_indent:
                current_bullet += ' ' + line.strip()
            else:
                # Not a continuation — save current bullet and reset
                cleaned = _clean_bullet(current_bullet)
                if cleaned and len(cleaned) > 5:
                    bullets.append(cleaned)
                current_bullet = None
                bullet_indent = None
        elif not line.strip() and current_bullet is not None:
            # Empty line ends the current bullet
            cleaned = _clean_bullet(current_bullet)
            if cleaned and len(cleaned) > 5:
                bullets.append(cleaned)
            current_bullet = None
            bullet_indent = None

    # Don't forget the last bullet
    if current_bullet:
        cleaned = _clean_bullet(current_bullet)
        if cleaned and len(cleaned) > 5:
            bullets.append(cleaned)

    # Fallback: if no bullet markers found, extract meaningful non-empty lines
    if not bullets:
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) > 10 and not stripped.startswith('#'):
                cleaned = _clean_bullet(stripped)
                if cleaned and len(cleaned) > 10:
                    bullets.append(cleaned)

    return bullets


def _clean_bullet(content: str) -> str:
    """Clean up a bullet point string."""
    content = content.strip()
    # Remove trailing markdown bold markers
    content = re.sub(r'\*\*$', '', content)
    return content.strip()


def extract_sources_from_markdown(markdown: str) -> List[Dict[str, Any]]:
    """
    Extract source citations from a markdown report.

    Looks for:
    - Markdown links: [title](url)
    - Plain URLs
    - Source sections with citations

    Args:
        markdown: The markdown text to extract from

    Returns:
        List of source dicts with 'title' and 'url' keys
    """
    if not markdown:
        return []

    sources = []
    seen_urls = set()

    # Extract markdown links [title](url)
    link_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
    for match in re.finditer(link_pattern, markdown):
        title = match.group(1).strip()
        url = match.group(2).strip()
        if url not in seen_urls:
            seen_urls.add(url)
            sources.append({"title": title, "url": url})

    # Extract plain URLs that weren't already captured
    url_pattern = r'(?<!\()(https?://[^\s\)>\]]+)'
    for match in re.finditer(url_pattern, markdown):
        url = match.group(1).strip()
        # Clean trailing punctuation
        url = re.sub(r'[.,;:]+$', '', url)
        if url not in seen_urls:
            seen_urls.add(url)
            # Try to extract domain as title
            domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
            title = domain_match.group(1) if domain_match else url
            sources.append({"title": title, "url": url})

    return sources


def format_market_data_report(summaries: Dict[str, Any], symbol: str = "") -> str:
    """
    Format market data summaries into a structured markdown report.

    Args:
        summaries: Dict containing quote_summary, indicators_summary, etc.
        symbol: The stock symbol being analyzed

    Returns:
        Formatted markdown report string
    """
    sections = []

    # Header
    header = f"## Market Data Analysis"
    if symbol:
        header += f" - {symbol}"
    sections.append(header)

    # Quote Summary
    quote_summary = summaries.get("quote_summary", "")
    if quote_summary:
        sections.append("\n### Price & Volume Data\n")
        sections.append(quote_summary)

    # Technical Indicators
    indicators_summary = summaries.get("indicators_summary", "")
    if indicators_summary:
        sections.append("\n### Technical Indicators\n")
        sections.append(indicators_summary)

    # Historical Data
    historical = summaries.get("historical_summary", "")
    if historical:
        sections.append("\n### Historical Performance\n")
        sections.append(historical)

    if len(sections) == 1:
        sections.append("\nNo market data available.")

    return "\n".join(sections)


def format_fundamentals_report(summaries: Dict[str, Any], symbol: str = "") -> str:
    """
    Format fundamentals summaries into a structured markdown report.

    Args:
        summaries: Dict containing overview, financials, valuation, etc.
        symbol: The stock symbol being analyzed

    Returns:
        Formatted markdown report string
    """
    sections = []

    # Header
    header = f"## Fundamental Analysis"
    if symbol:
        header += f" - {symbol}"
    sections.append(header)

    # Company Overview
    overview = summaries.get("overview", {})
    if overview:
        sections.append("\n### Company Overview\n")
        if isinstance(overview, dict):
            for key, value in overview.items():
                if value:
                    sections.append(f"- **{key.replace('_', ' ').title()}**: {value}")
        else:
            sections.append(str(overview))

    # Financials
    financials = summaries.get("financials", {})
    if financials:
        sections.append("\n### Financial Metrics\n")
        if isinstance(financials, dict):
            for key, value in financials.items():
                if value:
                    sections.append(f"- **{key.replace('_', ' ').title()}**: {value}")
        else:
            sections.append(str(financials))

    # Valuation
    valuation = summaries.get("valuation", {})
    if valuation:
        sections.append("\n### Valuation Metrics\n")
        if isinstance(valuation, dict):
            for key, value in valuation.items():
                if value is not None:
                    sections.append(f"- **{key.replace('_', ' ').upper()}**: {value}")
        else:
            sections.append(str(valuation))

    # Analyst Ratings
    analysts = summaries.get("analysts", {})
    if analysts:
        sections.append("\n### Analyst Ratings\n")
        if isinstance(analysts, dict):
            for key, value in analysts.items():
                if value:
                    sections.append(f"- **{key.replace('_', ' ').title()}**: {value}")
        else:
            sections.append(str(analysts))

    # Existing report text
    report = summaries.get("report", "")
    if report:
        sections.append("\n### Summary\n")
        sections.append(report)

    if len(sections) == 1:
        sections.append("\nNo fundamentals data available.")

    return "\n".join(sections)


def parse_sentiment(text: str) -> str:
    """
    Parse sentiment from text content.

    Args:
        text: Text to analyze for sentiment indicators

    Returns:
        One of: "bullish", "bearish", "neutral", "mixed"
    """
    if not text:
        return "neutral"

    text_lower = text.lower()

    bullish_indicators = [
        "bullish",
        "positive",
        "optimistic",
        "buy",
        "upgrade",
        "growth",
        "beat expectations",
        "strong",
        "outperform",
        "rally",
        "surge",
        "gain",
        "upside"
    ]

    bearish_indicators = [
        "bearish",
        "negative",
        "pessimistic",
        "sell",
        "downgrade",
        "decline",
        "miss expectations",
        "weak",
        "underperform",
        "drop",
        "fall",
        "loss",
        "downside",
        "concern"
    ]

    bullish_count = sum(1 for indicator in bullish_indicators if indicator in text_lower)
    bearish_count = sum(1 for indicator in bearish_indicators if indicator in text_lower)

    if bullish_count > bearish_count * 1.5:
        return "bullish"
    elif bearish_count > bullish_count * 1.5:
        return "bearish"
    elif bullish_count > 0 and bearish_count > 0:
        return "mixed"
    else:
        return "neutral"


def extract_symbols_from_text(text: str) -> List[str]:
    """
    Extract stock ticker symbols from text.

    Args:
        text: Text to search for symbols

    Returns:
        List of unique ticker symbols found
    """
    if not text:
        return []

    # Common patterns for tickers: $AAPL, (AAPL), AAPL:, "AAPL"
    patterns = [
        r'\$([A-Z]{1,5})\b',  # $AAPL
        r'\(([A-Z]{1,5})\)',  # (AAPL)
        r'\b([A-Z]{2,5})(?::|,|\s)',  # AAPL: or AAPL,
    ]

    symbols = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            symbol = match.group(1)
            # Filter out common non-ticker words
            if symbol not in {
                    'THE',
                    'AND',
                    'FOR',
                    'WITH',
                    'FROM',
                    'THIS',
                    'THAT',
                    'ARE',
                    'WAS',
                    'HAS',
                    'HAD',
                    'BUT',
                    'NOT',
                    'ALL',
                    'CAN',
                    'HER',
                    'WHO',
                    'GET',
                    'HIS',
                    'HAS'
            }:
                symbols.add(symbol)

    return list(symbols)


def create_standardized_output(research_report: str,
                               key_findings: Optional[List[str]] = None,
                               data_summary: Optional[Dict[str, Any]] = None,
                               sources: Optional[List[Dict[str, Any]]] = None,
                               status: str = "success") -> Dict[str, Any]:
    """
    Create a standardized output dict for research agents.

    Args:
        research_report: Full markdown report
        key_findings: List of 3-5 key finding strings
        data_summary: Agent-specific structured data
        sources: List of source dicts with title/url
        status: One of "success", "error", "no_data"

    Returns:
        Standardized output dict
    """
    # Auto-extract key findings if not provided
    if key_findings is None:
        key_findings = extract_key_findings_from_markdown(research_report)

    # Auto-extract sources if not provided
    if sources is None:
        sources = extract_sources_from_markdown(research_report)

    return {
        "research_report": research_report or "",
        "key_findings": key_findings or [],
        "data_summary": data_summary or {},
        "sources": sources or [],
        "status": status
    }
