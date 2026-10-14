-- "Job Finder" launcher. Built into "Job Finder.app" with build_app.sh.
-- Starts the site quietly in the background (if it isn't already running) and opens it in the browser.

property siteURL : "http://127.0.0.1:8000"

on siteIsUp()
	try
		do shell script "curl -s -o /dev/null --max-time 2 " & siteURL
		return true
	on error
		return false
	end try
end siteIsUp

on run
	launchJobFinder()
end run

on reopen
	launchJobFinder()
end reopen

on launchJobFinder()
	if not siteIsUp() then
		set appPath to POSIX path of (path to me)
		set folderPath to do shell script "dirname " & quoted form of appPath
		set q to quoted form of folderPath

		-- First time only: set up Python and the packages it needs.
		set needsSetup to (do shell script "cd " & q & " && if [ -f .venv/.installed ] && [ ! requirements.txt -nt .venv/.installed ]; then echo no; else echo yes; fi")
		if needsSetup is "yes" then
			display notification "Getting things ready for the first time. This takes about a minute." with title "Job Finder"
			try
				do shell script "cd " & q & " && ( [ -x .venv/bin/python ] || /usr/bin/python3 -m venv .venv ) && .venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt && touch .venv/.installed"
			on error
				display dialog "Job Finder couldn't finish setting up. Check that you're connected to the internet, then double-click Job Finder again." buttons {"OK"} default button 1 with icon caution with title "Job Finder"
				return
			end try
		end if

		-- Start the site in the background (no Terminal window).
		-- Only the site runs in the background; its output goes to a log so this launcher can quit right away.
		do shell script "cd " & q & " && mkdir -p data && { [ -f .env ] || cp .env.example .env; } && { NO_BROWSER=1 nohup .venv/bin/python run.py < /dev/null >> data/server.log 2>&1 & }"

		-- Wait for it to be ready (up to about 30 seconds).
		set ready to false
		repeat 60 times
			if siteIsUp() then
				set ready to true
				exit repeat
			end if
			delay 0.5
		end repeat
		if not ready then
			display dialog "Job Finder didn't start this time. Please try double-clicking it again." buttons {"OK"} default button 1 with icon caution with title "Job Finder"
			return
		end if
	end if

	open location siteURL
end launchJobFinder
