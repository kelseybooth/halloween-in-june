# Railway Setup Guide for Halloween Discord Bot

This guide walks you through setting up Railway for development and production hosting of your cat-petting Discord bot.

---

## What is Railway?

Railway is a deployment platform that makes hosting applications simple. It handles:
- Running your Python bot continuously
- Hosting a PostgreSQL database
- Managing environment variables
- Auto-deploying when you push code to GitHub
- Free tier with $5/month credit (perfect for testing)

---

## Step 1: Create a Railway Account

1. Visit https://railway.app
2. Sign up (you can use GitHub login, which is convenient)
3. Create a new project
4. Choose "GitHub" as your deployment method (you'll connect your repo next)

---

## Step 2: Connect Your GitHub Repository

1. In Railway, click "New Project" → "Deploy from GitHub"
2. Authorize Railway to access your GitHub account
3. Select your discord-bot repository
4. Railway will start watching for pushes to this repo

---

## Step 3: Add PostgreSQL Database to Your Railway Project

1. In your Railway project dashboard, click "New Service"
2. Select "Database" → "PostgreSQL"
3. Railway automatically provisions a PostgreSQL database
4. **Important:** Railway automatically adds `DATABASE_URL` environment variable
   - You can see it in the PostgreSQL service settings
   - Copy this value (you'll need it for local testing)

---

## Step 4: Add Your Discord Bot Token

1. In your Railway project dashboard, click "Variables"
2. Add a new variable:
   - **Key:** `DISCORD_TOKEN`
   - **Value:** Your Discord bot token (from Developer Portal)
3. Save the variables

---

## Step 5: Create a Procfile (Important!)

Railway needs to know how to start your bot. Create a file called `Procfile` in your project root:

**Procfile:**
```
worker: python bot.py
```

Add this to your repository and push to GitHub. Railway will restart automatically.

---

## Step 6: Test Locally Before Deploying

### Local Setup:

1. Create `.env` file in your project directory:
   ```
   DISCORD_TOKEN=your_bot_token_here
   DATABASE_URL=postgresql://user:password@host:port/dbname
   ```

2. To get the `DATABASE_URL` from Railway:
   - Go to your Railway PostgreSQL service
   - Click on it
   - Copy the connection string from the "Connect" tab
   - Paste it into your `.env` file

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Run locally:
   ```
   python bot.py
   ```

5. Test the bot in your Discord server:
   - `/pet` command
   - `/stats` command
   - Verify data appears in Railway PostgreSQL

6. Stop the bot and restart it. Check that data persists.

---

## Step 7: Push to GitHub and Deploy to Railway

Once everything works locally:

1. Make sure `Procfile` is committed and pushed
2. Make sure `.env` is in `.gitignore` (never commit secrets!)
3. Push your code to GitHub:
   ```
   git add .
   git commit -m "Add bot and database setup"
   git push
   ```

4. Railway automatically deploys! Watch the logs:
   - Go to your Railway project
   - Click on your service
   - View "Deployments" tab
   - Click the latest deployment to see logs

5. Once deployment succeeds, your bot runs 24/7 on Railway

---

## Debugging on Railway

**View Logs:**
- Go to your Railway project → service → "Logs" tab
- See real-time output from your bot
- Check for connection errors, command execution, etc.

**Check Environment Variables:**
- Click on the service
- Go to "Variables" tab
- Verify `DISCORD_TOKEN` and `DATABASE_URL` are set

**Restart the Bot:**
- Go to "Deployments" tab
- Click "Redeploy" on the latest deployment
- Bot restarts with latest code

**Check Database:**
- Click on PostgreSQL service
- Go to "Data" tab
- View your `users` table and verify data is being stored

---

## Cost & Free Tier

**Free Tier ($5/month credit):**
- Covers 1 Python bot + 1 PostgreSQL database
- More than enough for development and testing
- Can go to sleep if no activity (but bots keep activity going)

**For Production (100-500 users):**
- Estimated cost: $5-15/month
- Bot: ~$5-10/month (depending on resource usage)
- Database: ~$5/month (PostgreSQL)
- Total: Comfortable within budget

---

## Troubleshooting

**Bot doesn't start:**
1. Check logs for errors
2. Verify `Procfile` exists and is committed
3. Verify `DISCORD_TOKEN` environment variable is set
4. Restart deployment from Railway dashboard

**Database connection error:**
1. Verify `DATABASE_URL` is correct (copy from Railway)
2. Check that PostgreSQL service is running (green status in Railway)
3. Verify no typos in connection string

**Commands not working:**
1. Check bot logs for slash command registration errors
2. Verify Discord bot permissions are correct
3. Verify bot is in your test Discord server

**Data not persisting:**
1. Check that SQLAlchemy is creating tables (should see in logs on first run)
2. Verify database queries are executing (add logging in database.py)
3. Check PostgreSQL is actually storing data (view in Railway Data tab)

---

## Important Reminders

- 🔐 **Never commit your bot token to GitHub** — use `.env` + `.gitignore`
- 🔐 **Never hardcode DATABASE_URL** — read from environment variables
- 📝 **Add `Procfile` to repository** — Railway needs it to start your bot
- 📝 **Keep `.gitignore` updated** — exclude `.env` and `__pycache__`
- ⚡ **Use async database operations** — keeps Discord commands responsive
- 📊 **Monitor Railway logs regularly** — catch errors early

---

## Next Steps

1. Set up your Railway account and PostgreSQL database
2. Copy your `DATABASE_URL` from Railway
3. Update your `.env.example` with both `DISCORD_TOKEN` and `DATABASE_URL`
4. Pass the updated `DISCORD_BOT_MVP_SPEC.md` to Claude Code
5. Claude Code will implement the bot using this Railway setup

Happy coding! 🚀

