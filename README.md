# onChat

A minimal online multiplayer chat platform built with Flask and Socket.IO.

Features:
- Sign up / Log in
- Friends list
- Servers and channels
- Private servers (invite code)
- Real-time chat using Socket.IO

Databases:
- `users.db` stores users and friend relations
- `servers.db` stores servers, channels, and server members

Quick start (Windows PowerShell):

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 in your browser.

Public deployment

The app is ready to be hosted publicly. A simple option is to deploy it on Render, Railway, Fly.io, or a VPS.

Recommended deployment steps:
1. Push the project to GitHub.
2. Create a new web service on your hosting platform.
3. Set the start command to:

```bash
gunicorn app:app
```

4. Set the environment variable:
   - `PORT` = `10000` (or the platform's assigned port)
5. Make sure the host allows inbound traffic on port 80/443 and that your app binds to `0.0.0.0`.

If you use Render, the service will give you a public URL like:
- `https://your-app-name.onrender.com`

If you use Railway, the public URL will look like:
- `https://your-app-name.up.railway.app`