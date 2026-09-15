# Database Migrations

## Adding Indexes

To improve query performance, run the indexes migration script:

```bash
# Using psql
psql $DATABASE_URL -f system_app/migrations/add_indexes.sql

# Or using Python
python -c "from system_app.queries import query_db; exec(open('system_app/migrations/add_indexes.sql').read())"
```

## What These Indexes Do

- **Members table**: Speeds up searches by email, phone, name, and date queries
- **Attendance table**: Improves date-based queries and member lookups
- **Users table**: Faster authentication and user lookups
- **Pending edits**: Speeds up approval queue queries
- **Invoices**: Faster invoice lookups and date-based reports
- **Renewal logs**: Improves renewal history queries

## Performance Impact

After adding indexes, you should see:
- ⚡ Faster search queries (50-90% improvement)
- ⚡ Faster date-based filtering
- ⚡ Faster member lookups
- ⚡ Better performance on large datasets

## Monitoring

Check index usage with:
```sql
SELECT schemaname, tablename, indexname, idx_scan 
FROM pg_stat_user_indexes 
ORDER BY idx_scan DESC;
```

