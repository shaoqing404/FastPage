# Frontend Handoff For Gemini

This document is the handoff target after Phase 0 backend work for features 1-5 is complete.

## Frontend Objective

Build a simple Vite-based web application for:

- login
- PDF upload and management
- document version viewing and restore
- parse progress tracking
- chat skill CRUD
- document Q&A
- metrics display

## Frontend Assumptions

- backend already exposes stable REST APIs
- backend already returns parse and query status in machine-readable form
- no advanced security UX is required in the first frontend delivery

## Runtime Integration Rules

### API Base URL

- all backend endpoints use the prefix `/api/v1`
- frontend base URL must be configurable via `VITE_API_BASE_URL`

### Authentication

- use `Authorization: Bearer <token>`
- token is returned by the login endpoint
- store the token in `localStorage` in the first delivery

### Progress Refresh Strategy

- parsing and run progress use polling
- recommended polling interval: `2 seconds`
- continue polling until parse status becomes `index_ready` or `failed`

### Status Enums

`parse_status`:

- `uploaded`
- `queued`
- `parsing`
- `index_ready`
- `failed`

`ChatRun.status`:

- `accepted`
- `retrieving`
- `answering`
- `completed`
- `failed`

## Required Pages

### 1. Login Page

- hardcoded single-user login form
- token/session storage

### 2. Documents Page

- upload PDF
- list documents
- view active version and status
- open version history
- trigger parse / reparse
- restore version

### 3. Skills Page

- create skill
- edit prompt template
- choose target documents
- set model and request parameters
- delete skill

### 4. Chat Page

- choose document or skill
- enter question
- choose model
- display answer
- display selected sections and timings

### 5. Metrics Page

- parse job list
- query run list
- durations and status

## UX Notes

- keep UI operational and simple
- do not overdesign Phase 0
- emphasize status visibility for parsing and chat runs
- preserve identifiers needed for debugging

## Build Notes

- use `Vite`
- prefer a small component stack
- keep API client isolated behind one module
- allow environment-based backend base URL configuration
