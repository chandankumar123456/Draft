# Draft

### A Framework-Free Autonomous Coding Agent

> **Draft** is an autonomous coding agent that can understand software-development tasks, inspect a codebase, modify files, execute commands and tests, observe execution results, and iteratively work toward a verified solution — **implemented from the agent loop up rather than relying on an agent framework**.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python\&logoColor=white)](https://www.python.org/)
[![OpenAI Responses API](https://img.shields.io/badge/LLM-Responses%20API-black)](https://platform.openai.com/)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-purple)](https://modelcontextprotocol.io/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange)]()

---

## Overview

Most modern agent applications are assembled using orchestration frameworks that hide the mechanics of tool calling, state management, execution loops, and agent control.

**Draft takes the opposite approach.**

The project is built from the underlying primitives:

```text
LLM
  ↓
Decision
  ↓
Tool Call
  ↓
Application Executes Tool
  ↓
Tool Result
  ↓
LLM Observes Result
  ↓
Next Decision
  ↓
Repeat
```

The objective is not simply to make a chatbot that writes code.

The objective is to build a **closed-loop software engineering system** capable of:

* understanding a development goal
* exploring an unfamiliar repository
* searching and reading source code
* modifying files
* executing commands and tests
* interpreting failures
* iterating on its implementation
* verifying the result
* reporting exactly what was changed and verified

---

# Why "Draft"?

The name reflects the project's core philosophy:

> **Software is not finished when code is generated. It is finished when the result has been tested, observed, and verified.**

Draft represents that iterative process of turning an initial idea into working software.

---

# Core Philosophy

Draft is intentionally **framework-free at the agent layer**.

It does **not** depend on:

* LangChain
* LangGraph
* CrewAI
* AutoGen
* AGNO
* other agent orchestration frameworks

Instead, the project implements the core agent mechanics directly in Python.

This makes the internal architecture explicit:

```text
                    ┌──────────────┐
                    │     USER     │
                    └──────┬───────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │   LLM / AGENT    │
                  │                  │
                  │ Understand       │
                  │ Reason           │
                  │ Decide           │
                  └────────┬─────────┘
                           │
                     Tool Call
                           │
                           ▼
                  ┌──────────────────┐
                  │   TOOL ROUTER    │
                  └────────┬─────────┘
                           │
           ┌───────────────┼────────────────┐
           │               │                │
           ▼               ▼                ▼
      File Tools      Search Tools     Execution Tools
           │               │                │
           └───────────────┼────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ EXECUTION ENV.  │
                  │                  │
                  │ Filesystem       │
                  │ Shell            │
                  │ Tests            │
                  │ Git              │
                  └────────┬─────────┘
                           │
                           ▼
                     Tool Result
                           │
                           ▼
                         LLM
                           │
                           ▼
                    Next Decision
```

---

# The Agent Loop

The heart of Draft is a continuous decision-execution-feedback loop.

```text
         ┌─────────────┐
         │   Observe   │
         └──────┬──────┘
                ▼
         ┌─────────────┐
         │    Reason   │
         └──────┬──────┘
                ▼
         ┌─────────────┐
         │     Act     │
         └──────┬──────┘
                ▼
         ┌─────────────┐
         │   Verify    │
         └──────┬──────┘
                │
                └──────────────► Repeat
```

The model does not directly manipulate the computer.

Instead:

1. The LLM decides which action should be performed.
2. Draft receives the tool call.
3. Draft executes the corresponding Python implementation.
4. The execution result is returned to the LLM.
5. The LLM evaluates the result and determines the next action.
6. The loop continues until the task is completed or a control limit is reached.

This separation between **decision-making** and **execution** is fundamental to the project.

---

# Key Capabilities

## Repository Exploration

Draft can inspect a project before making changes.

Typical operations include:

```text
list_directory(path)
get_file_info(path)
```

This allows the agent to build an understanding of the repository structure instead of assuming where files exist.

---

## Code Search

Instead of reading an entire repository, the agent can search for relevant code.

Examples:

```text
search_code("authenticate")
search_code("database")
search_code("TODO")
```

This helps the agent locate:

* functions
* classes
* variables
* API routes
* tests
* configuration
* related implementation files

---

## File Operations

The agent can interact with source files through explicit tools.

Core operations include:

```text
read_file(path)
write_file(path, content)
```

More advanced editing can be implemented through patch-based operations so that modifications remain small and reviewable.

---

## Command Execution

A coding agent must be able to interact with the actual development environment.

Draft therefore exposes controlled execution capabilities such as:

```text
run_command(command)
run_tests(command)
```

Examples:

```text
pytest
python main.py
ruff check .
git diff
```

The important part is that command output becomes **new information for the agent**.

---

# The Self-Correction Loop

A major goal of Draft is to move beyond:

```text
Generate code → Stop
```

and instead support:

```text
Generate
   ↓
Execute
   ↓
Observe
   ↓
Detect failure
   ↓
Analyze
   ↓
Modify
   ↓
Execute again
   ↓
Verify
```

For example:

```text
User:
"Fix the authentication tests."
```

The agent may perform:

```text
list_directory(".")
        ↓
search_code("authentication")
        ↓
read_file("app/auth.py")
        ↓
read_file("tests/test_auth.py")
        ↓
write_file("app/auth.py")
        ↓
run_command("pytest")
        ↓
FAIL
        ↓
analyze failure
        ↓
modify implementation
        ↓
run_command("pytest")
        ↓
PASS
```

The agent should only report success after receiving evidence from the execution environment.

---

# Tool Architecture

Each tool has two sides.

### 1. Tool schema

The LLM needs a structured description of:

* tool name
* purpose
* parameters
* parameter types
* required arguments

### 2. Tool implementation

The Python application contains the actual implementation.

Conceptually:

```text
            Tool Schema
                 │
                 ▼
              LLM
                 │
                 │ function/tool call
                 ▼
          Tool Dispatcher
                 │
                 ▼
        Python Implementation
                 │
                 ▼
           Real System
                 │
                 ▼
           Structured Result
                 │
                 ▼
                LLM
```

This separation makes tools independently testable and easy to extend.

---

# Initial Toolset

Draft is designed around a small set of powerful primitives.

| Tool             | Purpose                         |
| ---------------- | ------------------------------- |
| `list_directory` | Explore files and directories   |
| `read_file`      | Read source/configuration files |
| `write_file`     | Create or modify files          |
| `search_code`    | Search the repository           |
| `run_command`    | Execute controlled commands     |
| `run_tests`      | Execute test suites             |
| `git_status`     | Inspect repository state        |
| `git_diff`       | Inspect modifications           |
| `git_log`        | Inspect recent history          |

Additional tools can be introduced without changing the core agent loop.

---

# Structured Tool Results

Draft does not rely on vague text-only tool responses.

Tools should return structured information.

Example:

```json
{
  "command": "pytest",
  "exit_code": 1,
  "stdout": "...",
  "stderr": "AssertionError: expected 200 but received 401",
  "duration_ms": 1450
}
```

A file operation might return:

```json
{
  "path": "app/auth.py",
  "success": true,
  "lines": 120
}
```

Structured results reduce ambiguity and make subsequent model decisions more reliable.

---

# State and Context

A coding agent needs more than isolated requests.

Draft maintains the information required for the agent to understand what has already happened.

Conceptually:

```text
User Request
      ↓
Agent Decision
      ↓
Tool Call
      ↓
Tool Result
      ↓
Agent Decision
      ↓
Tool Call
      ↓
Tool Result
      ↓
...
```

The state contains relevant information such as:

* user requests
* tool calls
* tool outputs
* execution errors
* previous actions
* final results

The application is responsible for managing this state and providing the required context to the model.

---

# Safety and Control

Autonomous execution requires boundaries.

Draft is designed around a controlled workspace rather than unrestricted machine access.

## Workspace Restriction

The agent should operate inside a designated project directory:

```text
workspace/
└── target-project/
```

Tool implementations should reject attempts to escape that workspace.

---

## Iteration Limits

The agent should never be allowed to loop indefinitely.

Example control:

```text
MAX_ITERATIONS = 20
```

When the limit is reached, the agent stops and reports that the task could not be completed within the allowed budget.

---

## Command Controls

Commands can be classified according to their risk.

```text
Low Risk
    read_file
    list_directory
    search_code

Medium Risk
    run_tests
    git_diff
    package installation

High Risk
    file deletion
    system modification
    git push
    destructive shell commands
```

High-risk operations should require explicit approval or be blocked completely.

---

## Human Approval

Draft can introduce an approval layer between the agent's decision and tool execution:

```text
Agent requests action
        ↓
Risk evaluation
        ↓
Allowed?
   ┌────┴────┐
   │         │
  YES       NO
   │         │
Execute   Ask User
             │
       ┌─────┴─────┐
       │           │
    Approve       Deny
       │           │
    Execute      Block
```

---

# Git-Aware Development

Git provides valuable context for an autonomous coding system.

Draft can use Git to understand:

```text
git status
git diff
git log
```

This allows the agent to determine:

* what changed
* which files were modified
* whether unexpected changes appeared
* what the current repository state is

A potential workflow is:

```text
Inspect
  ↓
Modify
  ↓
git diff
  ↓
Run tests
  ↓
Review
  ↓
Commit with approval
```

Destructive Git operations such as force-push should remain explicitly controlled.

---

# MCP Integration

Draft can also extend beyond local tools through the **Model Context Protocol (MCP)**.

MCP is treated as an extension mechanism rather than the foundation of the agent.

```text
                    CODING AGENT
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
         Local Tools            MCP Client
              │                     │
     ┌────────┼────────┐            │
     │        │        │            ▼
 filesystem  shell    Git       MCP Servers
                                   │
                         ┌─────────┼─────────┐
                         │         │         │
                       GitHub     Docs       DB
```

This allows Draft to interact with external systems while preserving the same underlying agent loop.

Potential MCP integrations include:

* GitHub
* documentation systems
* databases
* web/search services
* custom internal services

The agent still follows the same principle:

```text
Decide → Call Tool → Receive Result → Decide Again
```

---

# Example End-to-End Task

Suppose the user provides:

```text
Fix the failing authentication tests in this repository.
```

Draft may perform:

```text
1. Explore repository
2. Search for authentication logic
3. Inspect relevant source files
4. Inspect failing tests
5. Determine likely cause
6. Modify the implementation
7. Run tests
8. Observe failure
9. Refine implementation
10. Run tests again
11. Inspect git diff
12. Report verified result
```

Possible final response:

```text
Task completed.

Modified:
- app/auth.py

Verification:
- pytest
- 14 passed

Summary:
Fixed token validation logic responsible for the authentication failure.
```

---

# Architecture

```text
                          ┌─────────────────┐
                          │      USER       │
                          └────────┬────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │   Draft Agent     │
                         │      (LLM)        │
                         └─────────┬─────────┘
                                   │
                             Tool Calls
                                   │
                                   ▼
                         ┌───────────────────┐
                         │    Tool Router    │
                         └─────────┬─────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
               File Tools      Search Tools   Exec Tools
                    │              │              │
                    └──────────────┼──────────────┘
                                   │
                                   ▼
                           Local Workspace
                                   │
                            ┌──────┴──────┐
                            │             │
                         Files         Shell
                            │             │
                            └──────┬──────┘
                                   │
                                   ▼
                              Test Results
                                   │
                                   └───────────────► Agent

                                   │
                                   ▼
                              MCP Client
                                   │
                         ┌─────────┼─────────┐
                         ▼         ▼         ▼
                      GitHub    Docs        DB
```

---

# Suggested Project Structure

```text
Draft/
│
├── agent/
│   ├── loop.py
│   ├── state.py
│   ├── prompts.py
│   └── client.py
│
├── tools/
│   ├── filesystem.py
│   ├── search.py
│   ├── shell.py
│   ├── tests.py
│   ├── git.py
│   └── registry.py
│
├── mcp/
│   ├── client.py
│   └── servers.py
│
├── workspace/
│   └── target-project/
│
├── logs/
│
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

The structure can evolve as the implementation grows; the agent loop should remain independent from individual tools.

---

# Design Principles

### Framework-free agent core

The orchestration logic is written directly in Python rather than delegated to an agent framework.

### Tool-driven reasoning

The LLM interacts with the real environment through explicit tools.

### Closed-loop execution

Actions produce observations that influence subsequent decisions.

### Verification over assumption

The agent must inspect actual execution results before claiming success.

### Least privilege

Tools should have only the permissions required to perform their intended task.

### Deterministic execution layer

The LLM decides **what** should happen; application code determines **how** the requested operation is executed.

### Extensibility

New tools and MCP integrations should be addable without redesigning the agent loop.

---

# Technology Stack

| Layer                          | Technology                           |
| ------------------------------ | ------------------------------------ |
| Language                       | Python                               |
| LLM Interface                  | OpenAI-compatible Responses API      |
| Cloud Model Platform           | Microsoft Foundry / Azure            |
| Authentication                 | Azure Identity                       |
| Tool Calling                   | Function tools                       |
| External Tool Interoperability | Model Context Protocol (MCP)         |
| Repository Interaction         | Python filesystem + subprocess + Git |
| Configuration                  | Environment variables / `.env`       |
| Future UI                      | Textual                              |

The project does **not** use a dedicated agent orchestration framework.

---

# Development Roadmap

```text
M1  LLM Integration
        ↓
M2  Single Tool
        ↓
M3  Multiple Tools
        ↓
M4  Autonomous Agent Loop
        ↓
M5  Coding Workflow
        ↓
M6  Safety & Control
        ↓
M7  MCP Integration
        ↓
M8  Textual Interface
```

The first priority is the correctness of the underlying agent loop.

The user interface comes later.

---

# Running the Project

## Requirements

* Python 3.11+
* An OpenAI-compatible model deployment
* Azure credentials when using Microsoft Foundry / Azure
* Git
* A target repository placed inside the configured workspace

## Environment

Create a `.env` file based on:

```env
PROJECT_ENDPOINT=<your-project-endpoint>
MODEL_DEPLOYMENT=<your-model-deployment>
```

Authenticate through the supported Azure credential flow.

For example:

```bash
az login
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Start Draft

```bash
python main.py
```

The agent should then accept a natural-language software-development request and work against the configured workspace.

---

# Future Work

Potential extensions include:

* patch-based code editing
* repository indexing
* improved code search
* persistent task memory
* richer Git workflows
* automated linting and formatting
* multi-file change planning
* test selection
* tool permission policies
* MCP server discovery
* execution sandboxing
* task checkpoints and recovery
* Textual terminal interface
* execution traces and observability
* benchmark suite for coding tasks

---

# Engineering Highlight

The key engineering challenge in Draft is not simply connecting an LLM to a terminal.

It is implementing the machinery that turns a language model into a controlled software-engineering agent:

```text
                 ┌──────────────────────┐
                 │       LLM            │
                 │  Decision / Planning │
                 └──────────┬───────────┘
                            │
                       Tool Call
                            ▼
                 ┌──────────────────────┐
                 │   Python Runtime     │
                 │   Tool Execution     │
                 └──────────┬───────────┘
                            │
                         Result
                            ▼
                 ┌──────────────────────┐
                 │       LLM            │
                 │ Observe / Re-plan    │
                 └──────────┬───────────┘
                            │
                         Repeat
```

This makes Draft an exercise in **agent systems engineering**, rather than simply an API wrapper around an LLM.

---
