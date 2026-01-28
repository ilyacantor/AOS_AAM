# AAM - Adaptive API Mesh

## Overview

AAM (Adaptive API Mesh) is a self-healing integration mesh designed to help enterprises understand and manage their data pipelines. It addresses the common problem of unknown and unmanaged integration points spread across various platforms like iPaaS, API gateways, event buses, and data warehouses. AAM's core purpose is to observe and document existing integration fabrics, creating a single, comprehensive inventory of all data pipes with their metadata, health status, and ownership. It then self-heals when inconsistencies or issues (drift) are detected.

AAM's philosophy is to make data pipe behavior and meaning explicit without changing how data moves. It connects to enterprise Fabric Planes (like iPaaS, API Gateways, Event Buses, Data Warehouses) to inventory reusable data pipes, infer metadata, detect drift (e.g., schema changes, connectivity loss), and automatically self-heal connectivity issues. It also publishes a clean pipe inventory for downstream systems. AAM does not move or transform data, act as an iPaaS replacement, build per-app SaaS connectors, or handle infrastructure operations.

Key capabilities include Fabric Plane Connectivity, Pipe Discovery, Pipe Inference, Self-Healing, Enterprise Maturity Presets, Governance Enforcement, and a Candidate Workflow for new data sources.

## User Preferences

- **Communication style**: Simple, everyday language
- **Development principle**: Foundational fixes only (no workarounds)
- **Development approach**: Iterative, small frequent updates
- **Interaction**: All operations via UI or Swagger (`/docs`)

## System Architecture

AAM is structured around distinct component boundaries: AAM (the Mesh) owns self-healing and repair; Farm acts as a test oracle; DCL (the Brain) handles metadata only; and AOA (the Orchestrator) manages execution and infrastructure.

The application is built using a modern Python stack:
- **FastAPI**: For the asynchronous web framework and automatic OpenAPI documentation.
- **SQLite**: As an embedded database (`aam.db`).
- **Pydantic**: For data validation and modeling.
- **Uvicorn**: As the ASGI server.

The application structure is modular, separating concerns into `main.py` (FastAPI app, endpoints, UI), `models.py` (Pydantic models), `db.py` (SQLite operations), `inference.py` (observation processing), `preset_config.py` (enterprise presets), `fabric_drift.py` (drift logic), and an `adapters/` directory containing abstract base classes and specific implementations for iPaaS, API Gateway, Event Bus, and Data Warehouse integrations. A `collectors/` directory includes mock collectors for testing.

UI/UX decisions focus on a practical operator interface, offering screens for Topology, Pipes Inventory, Pipe Detail, Candidates, Drift & Health, and an in-app Guide. This interface supports essential operator jobs: seeing existing pipes, identifying issues, and taking bounded actions like running collectors, acknowledging drift, or exporting data. Operators can run collectors, view and filter pipe inventory, manage candidates, acknowledge/suppress drift alerts, export pipes, and switch between enterprise presets. By design, operators cannot automatically fix schema drift, provision new connectors, rotate secrets, or deploy TEE infrastructure, maintaining AAM's focus on observation and documentation.

## External Dependencies

AAM integrates with various enterprise integration platforms, referred to as "Fabric Planes," by observing their existing functionalities rather than replacing them.

- **iPaaS Platforms**: Connects to platforms like Workato and MuleSoft to receive webhook signals about recipe changes.
- **API Gateways**: Integrates with solutions such as Kong, Apigee, and AWS API Gateway to read API catalogs and traffic patterns.
- **Event Buses**: Subscribes to schema registries and topic metadata from systems like Kafka, EventBridge, and Pulsar.
- **Data Warehouses**: Reads table schemas and freshness metadata from data warehouses such as Snowflake, BigQuery, and Redshift.
- **DCL (Data Catalog Layer)**: AAM exports clean pipe inventory data to DCL for downstream metadata consumption.
- **AOD (Automated Operations Dashboard)**: Receives ConnectionCandidates from AOD, which represent potential new data sources for AAM to process.