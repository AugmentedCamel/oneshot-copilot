# Procedure Plugins and Concurrency

This document describes how to configure procedure execution for different use cases ("plugins").

## Concurrency Policies

When starting a procedure via the `/api/v2/procedures/start` endpoint, you can specify a `policy` to control how it interacts with existing procedures for the same user and camera.

### Available Policies

| Policy | Description | Use Case |
| :--- | :--- | :--- |
| `replace` | **Default**. Aborts any currently running procedure for the user/source and starts the new one immediately. | Strict workflows where focus is required (e.g., Smart Glasses Instructions). |
| `parallel` | Starts the new procedure alongside any existing ones. Both will process frames. | Background tasks or auxiliary monitoring (e.g., Safety Monitoring). |
| `queue` | If a procedure is running, adds the new one to a queue. It will start automatically when the current one completes. | Sequential checks (e.g., Quality Control Pipeline). |

## Examples

### Smart Glasses Instructions
**Goal**: Guide a user through a complex task.
**Configuration**: Use `policy="replace"`.
**Reasoning**: The user should only see instructions for one task at a time to avoid confusion.

```json
POST /api/v2/procedures/start
{
  "username": "operator_1",
  "procedure_id": "pizza_pepperoni@v1",
  "policy": "replace"
}
```

### Quality Control Pipeline
**Goal**: Run a series of automated checks on a product.
**Configuration**: Use `policy="queue"`.
**Reasoning**: Checks should happen in a specific order. If "Check A" is running, "Check B" should wait until A finishes.

```json
POST /api/v2/procedures/start
{
  "username": "qc_station_1",
  "procedure_id": "check_crust@v1",
  "policy": "queue"
}
```

### Safety Monitoring
**Goal**: Continuously monitor for safety hazards while other tasks are performed.
**Configuration**: Use `policy="parallel"`.
**Reasoning**: Safety checks should run in the background regardless of what the user is doing.

```json
POST /api/v2/procedures/start
{
  "username": "operator_1",
  "procedure_id": "safety_monitor@v1",
  "policy": "parallel"
}
```
