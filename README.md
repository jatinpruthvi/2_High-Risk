# Institutional Options Paper System

Phase 1 implementation foundation for the multi-instrument option-buying operating system.

## Current scope

- Paper-mode only
- No live orders
- No broker execution
- Maximum one simulated open position
- MTIL-first logging and research architecture

## Quick validation

```bash
python -m institutional_options
python -m unittest discover -s tests
```
