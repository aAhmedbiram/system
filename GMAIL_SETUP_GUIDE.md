# Gmail Setup Guide for Email Sending

## Important: You MUST use a Gmail App Password (not your regular password)

The password `01147216302` you're using is NOT a valid Gmail App Password. Gmail App Passwords are 16 characters long and look like: `abcd efgh ijkl mnop`

## Steps to Set Up Gmail for Email Sending:

### 1. Enable 2-Step Verification (Required)
1. Go to your Google Account: https://myaccount.google.com/
2. Click on **Security** in the left sidebar
3. Under "Signing in to Google", click **2-Step Verification**
4. Follow the steps to enable it (you'll need your phone)

### 2. Generate an App Password
1. Go to: https://myaccount.google.com/apppasswords
2. Or: Google Account → Security → 2-Step Verification → App passwords
3. Select "Mail" as the app
4. Select "Other (Custom name)" as the device, type "Rival Gym System"
5. Click **Generate**
6. Copy the 16-character password (it will look like: `abcd efgh ijkl mnop`)
7. **Remove the spaces** when using it (so it becomes: `abcdefghijklmnop`)

### 3. Update Your Code
Replace the password in your code with the App Password you just generated.

### 4. Alternative: Enable "Less Secure App Access" (NOT RECOMMENDED)
⚠️ **Warning**: This is less secure and Google may disable it. Use App Passwords instead.

If you must use this (not recommended):
1. Go to: https://myaccount.google.com/lesssecureapps
2. Turn on "Allow less secure apps"
3. Note: This may not work if 2-Step Verification is enabled

## Network Issues

If you're getting "Network is unreachable" errors:
- Your server cannot connect to Gmail's SMTP servers
- Check firewall settings on your server
- Contact your hosting provider to allow outbound SMTP connections
- Ports 587 and 465 need to be open for outbound connections

## Testing

After setting up, test by sending an email. The error messages will tell you if:
- Authentication failed → Wrong password or App Password not set up
- Network unreachable → Server can't connect to Gmail (firewall/network issue)

