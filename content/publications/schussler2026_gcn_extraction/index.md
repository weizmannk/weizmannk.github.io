---
title: AI-Assisted Extraction of Follow-up Observations from GCN Circulars in Astro-COLIBRI
authors:
- F. Schüssler
- others
date: '2026-01-01T00:00:00Z'
publication_types:
- submitted
publication_years:
- '2026'
featured: false
tags:
- core-team
sort_key: '12026'
abstract: We present a new Astro-COLIBRI component that converts free-text GCN Circulars
  into structured, event-linked follow-up records and combines them with structured
  reports submitted directly by the community. A continuously running Circular listener
  associates new reports with transient events, applies deterministic pre-analysis,
  and invokes a schema-constrained large language model extraction step for photometry,
  contacts, redshifts, and other reported results and metadata. The resulting records
  are submitted to the Astro-COLIBRI API, normalized into a common event-level follow-up
  database, and exposed through the web and mobile interfaces as report summaries,
  contact tools, optical-afterglow context figures, and downloadable CSV or VOTable
  products. After tuning, all 1,775 Circulars of an operational evaluation corpus
  covering the first half of 2026 completed the workflow without failures. An internal
  human audit of 210 Circulars confirmed 25,827 of 25,880 definite field-level decisions
  (99.80%), with the remaining errors confined to observation timing and facility
  attribution in eight of 231 assessed reports. Extracted redshifts agree with the
  independent GRBweb compilation for 228 of the 249 events the two share, and every
  disagreement traces to a limit, a candidate-host estimate, or a value later refined
  rather than to a misread Circular. The final pipeline was applied to the full GCN
  archive since 2016, yielding 68,393 individual observations from 26,811 reports
  across 5,787 transient events, and is now running in real time on new Circulars.
  The reusable parsing and normalization pipeline is released as the open-source Python
  package astro-colibri-circular-parser. This paper describes the scientific motivation,
  architecture, extraction schema, quality-control safeguards, user-facing products,
  and current use-cases of the system.
hugoblox:
  ids:
    doi: 10.48550/arXiv.2608.23270
    arxiv: '2608.23270'
---
