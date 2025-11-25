# Debugging Guide - Internal Server Error

## Step-by-Step Debugging Process

### 1. Check the Console/Logs
When an internal server error occurs, check your console/terminal where Flask is running. You should see detailed error information including:
- Error type
- Error message
- Full traceback
- Request details (method, path, form data)

### 2. Use the Debug Endpoint
Visit: `http://localhost:5000/debug/test`
This will show:
- Application status
- Database connection status
- Current timestamp

### 3. Check Error Page
When an error occurs, you'll see a user-friendly error page with:
- Error code (500, 404, etc.)
- Error message
- Troubleshooting tips

### 4. Common Issues and Solutions

#### Database Connection Issues
- **Symptom**: "Failed to connect to database"
- **Solution**: Check `DATABASE_URL` environment variable
- **Test**: Visit `/debug/test` to check database connection

#### Import Errors
- **Symptom**: "No module named X"
- **Solution**: Install missing packages: `pip install -r requirements.txt`

#### CSRF Token Errors
- **Symptom**: "CSRF token missing"
- **Solution**: Make sure forms include `{{ csrf_token() }}`

#### Email Sending Errors
- **Symptom**: "SMTP Authentication Error"
- **Solution**: 
  - Use Gmail App Password (not regular password)
  - Enable 2-Step Verification
  - Generate App Password at: https://myaccount.google.com/apppasswords

#### Missing Template Errors
- **Symptom**: "Template not found"
- **Solution**: Check that all template files exist in `templates/` folder

### 5. Enable Verbose Logging
The app now logs:
- Every request (method, path, IP)
- All exceptions with full tracebacks
- Database operations
- Email sending attempts

### 6. Test Individual Routes
Try accessing routes one by one to identify which route causes the error:
- `/` - Home page
- `/login` - Login page
- `/signup` - Signup page
- `/debug/test` - Debug endpoint

### 7. Check Environment Variables
Make sure these are set (if needed):
- `DATABASE_URL` - PostgreSQL connection string
- `SECRET_KEY` - Flask secret key
- `GMAIL_APP_PASSWORD` - Gmail app password
- `BASE_URL` - Base URL for email links (production)

### 8. Database Schema Issues
If you see column errors:
- Run the app once to auto-create tables
- Check `queries.py` `create_table()` function
- Verify database migrations

## Quick Debug Checklist

- [ ] Check console logs for error details
- [ ] Visit `/debug/test` to verify app is running
- [ ] Check database connection
- [ ] Verify all required packages are installed
- [ ] Check environment variables
- [ ] Verify template files exist
- [ ] Test individual routes
- [ ] Check for syntax errors in code

## Getting Help

When reporting an error, include:
1. Full error traceback from console
2. Request details (URL, method, form data)
3. Steps to reproduce
4. Environment (local/production)
5. Python version
6. Package versions

