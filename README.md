# Value Leakage Pilot (Corrected)

This repository contains the corrected implementation of the 52-call value leakage pilot.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set your Groq API key in the environment or `.env`:
   ```bash
   export GROQ_API_KEY=your_key
   ```

## Preflight

To verify the configuration, schedule, and prompts without making API calls:
```bash
python -m src.experiment --preflight
```
This generates the schedule in `pilot_schedule_v2.json` and the manifest in `pilot_manifest_v2.json`.

## Execution

To execute the experiment and make API calls (respecting rate limits and creating checkpoints):
```bash
python -m src.experiment --execute
```
Outputs are logged to `pilot_log_v2.jsonl`. 

## Resumption

If execution halts due to rate limits or transport errors, simply rerun:
```bash
python -m src.experiment --execute
```
The script will safely resume from `pilot_log_v2.jsonl` using the checkpoints. It verifies that prompt text, configuration, and model have not changed.

## Analysis

To generate the technical and descriptive audit report:
```bash
python -m src.analyze --log pilot_log_v2.jsonl
```
