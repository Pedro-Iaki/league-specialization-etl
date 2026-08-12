# League Specialization ETL

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Status](https://img.shields.io/badge/extraction-operational-brightgreen)
![Status](https://img.shields.io/badge/transformation-in%20development-yellow)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

An ETL pipeline built around the Riot Games API to investigate the relationship between champion specialization, gameplay patterns, and player performance in League of Legends.

The project is also an exercise in building a data pipeline with production-oriented concerns: concurrency, state management, failure recovery, data quality, traceability, and efficient API consumption.

> **Status:** Extraction is operational. Transformation is currently under development.

## Table of Contents

- [Motivation](#motivation)
- [Architecture](#architecture)
- [Current Features](#current-features)
- [Data Flow](#data-flow)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)
- [Technology](#technology)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)
- [Disclaimer](#disclaimer)

## Motivation

How does a player's specialization affect their performance?

The goal is to investigate the relationship between gameplay patterns and player success by analyzing factors such as:

- Champion specialization and mastery
- Win rate
- Rank and rank progression
- Recent activity
- Champion population across tiers
- Champion selection patterns
- Other relevant player and champion characteristics

The analytical goal is to identify relationships between strategy and performance, rather than assume direct causality.

## Architecture

The pipeline is currently structured as an ETL, with a roadmap toward an ELT architecture using Airflow and dbt/Postgres.

```text
                    Riot Games API
                          │
                          ▼
                  ┌───────────────┐
                  │   Extraction  │
                  │               │
                  │ • Pagination  │
                  │ • Rate Limit  │
                  │ • Retry       │
                  │ • Concurrency │
                  └───────┬───────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │      Bronze     │
                 │                 │
                 │ Raw API data    │
                 │ Partitioned     │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │ Operational DB  │
                 │                 │
                 │ Runs / Tasks    │
                 │ State / Errors  │
                 │ Metadata        │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │     Silver      │
                 │                 │
                 │ Validation      │
                 │ Consolidation   │
                 │ Partitioning    │
                 │ Quarantine      │
                 └────────┬────────┘
                          │
                          ▼
                    Gold / Analytics
                       (roadmap)
```

The operational database acts as the source of truth for pipeline state, allowing executions to be tracked and recovered without blindly reprocessing previously completed work.

## Current Features

**Incremental, state-driven extraction**
- Extraction is driven by persisted pipeline state rather than treating every execution as a completely new run
- Runs and individual tasks are tracked through the operational database, so the pipeline knows what has already been processed and what still requires action

**Concurrent extraction**
- The extraction layer uses multithreading to process independent tasks concurrently
- Shared state is explicitly synchronized, with dedicated tests covering concurrent execution and potential race conditions

**Dynamic rate limiting**
- API consumption is controlled through token buckets whose limits are derived from the API's available rate limits
- The objective is to maximize throughput while respecting Riot's API constraints

**Failure handling and recovery**
- Transient API failures are handled through retries with exponential backoff
- Pipeline failures are persisted as operational state, so failed work can be identified and recovered without restarting the entire pipeline
- Stalled executions can also be detected and marked accordingly

**Data validation and integrity**
- Pydantic validation
- Database constraints
- Integrity checks
- File tracking
- Output validation
- Automated tests
- Quarantine of invalid records
- The transformation layer also checks for raw files that exist on disk but are not registered in the expected pipeline state

**Data lineage**
- The operational database tracks the relationship between pipeline runs, tasks, generated files, and their associated metadata
- This provides lineage from processed data back to the execution that produced it

**Partitioned data**
- Data is organized according to Data Lake patterns and partitioned by relevant dimensions: `region/`, `queue/`, `patch/`
- The Silver layer is written as Parquet datasets

## Data Flow

The extraction layer currently produces raw datasets for players and champion masteries. The transformation layer consolidates these datasets into structured Silver tables while separating invalid records into quarantine datasets.

A simplified layout:

```text
data/
├── raw/ # Unprocessed, extracted from the src/extract scripts
│   ├── players/
│   └── masteries/
│
├── silver/ # Cleaned parquets, but not yet setup for analysis
│   ├── players/
│   ├── masteries/
│   └── assurance/
│
├── quarantine/ # Files or records that couldn't be salvaged
│   ├── players_invalid.parquet
│   └── masteries_invalid.parquet
│
└── database/ # Local orchestration databases for each step
    ├── extraction.db
    └── transform.db
```

## Getting Started

### Requirements

- Python 3.11+
- A Riot Games API key ([developer.riotgames.com](https://developer.riotgames.com))

### Installation

```bash
git clone https://github.com/<your-username>/league-specialization-etl.git
cd league-specialization-etl

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the project itself in editable mode
pip install -e .
```

### Configuration

Change the file at:

```bash
config/EXTRACTION_CONFIG.env
```

### Running the pipeline (Currently only extracts)

```bash
python src/extract/run_pipeline.py
```

> Extraction is fully operational today. Transformation (`run_transform.py`) is under active development — expect incomplete output until the Silver layer is finalized.

## Configuration Reference

Pipeline behavior is configured through environment variables rather than hardcoded execution parameters.

```env
RIOT_API_KEY=your_api_key_here
VERSION=0.8.4
PLAYERS_FETCH_DEPTH=30
FULL_VERIFICATION_POST=True
REGION=na1
QUEUE=RANKED_SOLO_5x5
TIERS=DIAMOND,EMERALD,PLATINUM,GOLD,SILVER,BRONZE,IRON
DIVISIONS=I,II,III,IV
```

**The API key should never be committed to the repository.** Keep `EXTRACTION_CONFIG.env` in `.gitignore`.

## Testing

The project includes tests covering the operational behavior of the pipeline:

- Environment and configuration validation
- Database operations
- File naming and partitioning
- Output generation
- Pagination
- Integrity checks
- Cleanup behavior
- Concurrent execution
- Player extraction
- Champion mastery extraction

Concurrency tests specifically execute multiple workers against shared pipeline state to verify that concurrent runs do not corrupt files or database state.

```bash
pytest
```

## Technology

| Category | Tools |
|---|---|
| Language | Python |
| Storage | SQLite, Parquet |
| Data processing | Pandas, PyArrow, Pydantic |
| Networking | Requests, Tenacity |
| Concurrency | ThreadPoolExecutor |
| Logging | Loguru |
| Testing | Pytest |

## Project Structure

```text
├── config/
│   └── EXTRACTION_CONFIG.env
│
├── sandbox/
│   ├── Initial_Cleaning.py
│   └── Transformation_Experiments.py
│
├── src/
│   ├── extract/
│   │   ├── tests/
│   │   ├── api_client.py
│   │   ├── api_client_protocol.py
│   │   ├── extraction_db_helper.py
│   │   ├── extraction_schemas.sql
│   │   ├── get_masteries.py
│   │   ├── get_players.py
│   │   ├── init_extraction_db.py
│   │   ├── output_helper.py
│   │   ├── run_pipeline.py
│   │   └── verify_integrity.py
│   │
│   ├── transform/
│   │   ├── tests/
│   │   ├── consolidate_silver.py
│   │   ├── init_transform_db.py
│   │   ├── run_transform.py
│   │   ├── transform_db_helper.py
│   │   └── transform_schemas.sql
│   │
│   ├── load/
│   └── pydantic_models.py
│
├── data/
├── README.md
├── pyproject.toml
├── requirements.txt
└── TODO
```

## Roadmap

The current focus is completing and stabilizing the transformation layer.

**Near-term**
- Completing Silver transformations
- Additional data quality checks
- Expanded integration tests

**Analytics (Gold layer)**
- Champion specialization metrics
- Rank progression analysis
- Champion population analysis
- Performance analysis

**Platform evolution**
- Migration of orchestration to Airflow
- Migration of transformations toward dbt
- Migration from SQLite to Postgres
- Evolution from ETL toward ELT

## License

This project is provided under the MIT license. See "MIT license" tab at the top for more information.

## Disclaimer

This project is an independent data engineering project using publicly available Riot Games API services.

League of Legends and Riot Games are trademarks of Riot Games, Inc. This project is not affiliated with or endorsed by Riot Games.
