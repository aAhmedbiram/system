# Local Development and Testing Environment Setup

This document describes how to configure, switch between, and run different environments (Production, Development, Testing) for the Rival Gym System Flask application.

---

## 🔒 Safety and Isolation Rules

To prevent accidental modification of production data, the application enforces the following safety controls:

1. **Production Database Debug Guard:**
   If the application is running in **Debug Mode** (e.g. running via `python app.py` with standard development configurations) while connected to the production database host (`ep-still-union-a4fzfij8.us-east-1.aws.neon.tech`), the startup is immediately aborted with a fatal error:
   ```
   Debug mode cannot run against the Production database.
   ```
   This prevents local debug servers from accessing or corrupting production data. This protection does not affect production deployments running with Gunicorn or other WSGI servers.

2. **Startup Environment Banners:**
   When starting up, the system prints clear banners reflecting the database environment status:
   - **TEST:**
     ```
     ====================================
     RUNNING IN TEST DATABASE
     ====================================
     ```
   - **PRODUCTION:**
     ```
     ====================================
     RUNNING IN PRODUCTION
     Connected Database: neondb
     ====================================
     ```

---

## 📂 Environment Files Configuration

The application uses different configuration files depending on the `APP_ENV` environment variable:

- **`.env.development`** (loaded when `APP_ENV=DEV` or unset): Contains development configuration.
  For local development, the database connection string is:
  ```
  DATABASE_URL=postgresql://db_user_dev:db_password_dev@localhost:5432/rival_gym_dev?sslmode=disable
  ```
  Note: `db_password_dev` is used as a documented local-only credential.
- **`.env.testing`** (loaded when `APP_ENV=TEST`): Contains testing configuration.
  For local testing, the database connection string is:
  ```
  DATABASE_URL=postgresql://db_user_test:db_password_test@localhost:5432/rival_gym_testing?sslmode=disable
  ```
- **`.env`** (loaded when `APP_ENV=PRODUCTION`): Contains production configuration. The production `DATABASE_URL` specifies `sslmode=require` (e.g. Neon DB), ensuring all transport is encrypted.

An example template is available at [`.env.example`](file:///home/ahmedbiram/system/.env.example).

---

## 🐘 Creating a Neon Test/Dev Database

To create a completely separate database for testing/development, you have two options in Neon:

### Option A: Create a Database on the Same Project (Recommended for Simple Testing)
This is simple, free, and uses the same Postgres compute instance.
1. Go to the [Neon Console](https://console.neon.tech).
2. Select your project.
3. Click on the **Databases** tab in the left sidebar.
4. Click **Create Database**.
5. Set the name to `rival_gym_testing` (or `rival_gym_dev`).
6. Click **Create**.
7. Copy the connection string. It will look like this (only the database name at the end changes):
   ```
   postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require
   ```

### Option B: Create a Branch (Neon Best Practice for isolated data)
Neon allows creating instant, zero-copy database branches that clone both schema and data instantaneously.
1. In the Neon Console, go to the **Branches** tab.
2. Click **Create Branch**.
3. Name the branch `testing`.
4. Choose the parent branch (`main`).
5. Click **Create Branch**.
6. This gives you a completely isolated database URL with its own credentials that contains the exact schema and data from production at that moment, with zero initial storage overhead.

---

## 🗄️ SQL Schema & Data Dumps

To clone your production database to your local or testing environment:

1. **Schema Dump:**
   The production schema has been dumped to [`production_schema.sql`](file:///home/ahmedbiram/system/production_schema.sql).
2. **Data Dump:**
   The production data has been dumped to [`production_data.sql`](file:///home/ahmedbiram/system/production_data.sql).

### How to Import Schema & Data into your Test/Dev Database:

Run the following commands in your terminal (replace `<test_database_url>` with your separate test database connection string):

```bash
# 1. Restore the schema (tables, constraints, indexes)
psql "<test_database_url>" -f production_schema.sql

# 2. Restore all data
psql "<test_database_url>" -f production_data.sql
```

---

## 🚀 Running the Application

### 1. Running in Development Mode (DEV)
Loads `.env.development` (points to your local/development database).
```bash
# Set environment
export APP_ENV=DEV

# Run Flask as module
python -m system_app.app
```

### 2. Running in Testing Mode (TEST)
Loads `.env.testing` (points to your separate test database).
```bash
# Set environment
export APP_ENV=TEST

# Run Flask as module
python -m system_app.app
```

### 3. Running in Production Mode (PRODUCTION)
Loads `.env` (or system environment variables).
```bash
# Set environment
export APP_ENV=PRODUCTION

# Run Gunicorn (production WSGI server)
gunicorn system_app.app:app --bind 0.0.0.0:5000
```
