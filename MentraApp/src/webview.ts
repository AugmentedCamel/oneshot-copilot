import { AuthenticatedRequest, AppServer } from '@mentra/sdk';
import express, { Response, NextFunction } from 'express';
import path from 'path';

// Track recent TTS requests to prevent duplicates (username -> last text + timestamp)
const recentTTSRequests = new Map<string, { text: string; timestamp: number }>();
const TTS_DUPLICATE_WINDOW_MS = 2000; // 2 second window for duplicate detection

/**
 * Sets up all Express routes and middleware for the server
 * @param server The server instance
 */
export function setupExpressRoutes(server: AppServer): void {
  // Get the Express app instance
  const app = server.getExpressApp();

  // Set up EJS as the view engine
  app.set('view engine', 'ejs');
  app.engine('ejs', require('ejs').__express);
  app.set('views', path.join(__dirname, '../views'));

  // Middleware to parse JSON bodies
  app.use(express.json());

  // Register a route for the login page with username persistence
  app.get('/login', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userId = req.authUserId;
      const timestamp = new Date().toISOString();

      console.log(`[${timestamp}] Login route accessed by userId: ${userId}`);

      // If no userId, just show login form
      if (!userId) {
        console.log(`[${timestamp}] No userId provided - showing login form`);
        return res.render('login_view', { userId: null });
      }

      // Get server instance to access maps and methods
      const userNamesMap = (server as any).getUserNamesMap();

      // Step 1: Check if username exists for this userId
      const existingUsername = userNamesMap.get(userId);

      if (!existingUsername) {
        console.log(`[${timestamp}] No existing username for userId: ${userId} - showing login form`);
        return res.render('login_view', { userId });
      }

      console.log(`[${timestamp}] Found existing username "${existingUsername}" for userId: ${userId}`);

      // Step 2: Verify ownership - check if this username is still owned by this userId
      const currentOwner = (server as any).getUserIdForUsername(existingUsername);

      if (currentOwner !== userId) {
        console.warn(`[${timestamp}] Username "${existingUsername}" ownership mismatch! Expected userId: ${userId}, but found: ${currentOwner}. Username was taken by another device. Cleaning up stale binding.`);
        userNamesMap.delete(userId);
        console.log(`[${timestamp}] Stale binding removed for userId: ${userId} - showing login form`);
        return res.render('login_view', {
          userId,
          message: 'Your username is in use on another device. Please login again.'
        });
      }

      // Step 3: Check user state
      const userState = (server as any).getUserState(existingUsername);

      console.log(`[${timestamp}] Username "${existingUsername}" state: ${userState}`);

      // Step 4: Route based on state
      switch (userState) {
        case 'IDLE':
          console.log(`[${timestamp}] User "${existingUsername}" is IDLE - redirecting to /webview`);
          return res.redirect('/webview');

        case 'WORKING':
          const activeProcedure = (server as any).getActiveProcedure(existingUsername);
          console.log(`[${timestamp}] User "${existingUsername}" has active session with procedure: ${activeProcedure || 'unknown'} - redirecting to taskview`);

          if (activeProcedure) {
            return res.redirect(`/taskview?procedure=${encodeURIComponent(activeProcedure)}`);
          }

          // Fallback if no procedure stored (shouldn't happen in normal flow)
          console.warn(`[${timestamp}] No active procedure found for WORKING user "${existingUsername}" - redirecting to default taskview`);
          return res.redirect('/taskview');

        case 'OFFLINE':
          console.warn(`[${timestamp}] User "${existingUsername}" is OFFLINE (unexpected state) - cleaning up and showing login form`);
          userNamesMap.delete(userId);
          // Note: The username-to-userId binding will be cleaned up automatically by unbindUsername if needed
          (server as any).setUserState(existingUsername, undefined); // Remove from userStates
          console.log(`[${timestamp}] Stale bindings cleaned for userId: ${userId}`);
          return res.render('login_view', {
            userId,
            message: 'Session expired. Please login again.'
          });

        default:
          console.error(`[${timestamp}] Unknown user state "${userState}" for username "${existingUsername}" - showing login form as fallback`);
          return res.render('login_view', { userId });
      }
    } catch (error) {
      const timestamp = new Date().toISOString();
      console.error(`[${timestamp}] Error in /login route:`, error);
      return res.render('login_view', {
        userId: req.authUserId || null,
        message: 'An error occurred. Please try again.'
      });
    }
  }) as any);

  // Register a route for handling webview requests
  app.get('/webview', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    if (req.authUserId) {
      // Render the webview template
      res.render('mainwebview', {
        userId: req.authUserId,
      });
    } else {
      res.render('mainwebview', {
        userId: undefined,
      });
    }
  }) as any);

  // Register a route for the task view page
  app.get('/taskview', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    const procedure = req.query.procedure as string || 'scavenge hunt';

    if (req.authUserId) {
      res.render('taskview', {
        userId: req.authUserId,
        procedure: procedure,
      });
    } else {
      res.render('taskview', {
        userId: undefined,
        procedure: procedure,
      });
    }
  }) as any);

  // POST endpoint to save user login name
  app.post('/api/save-login-name', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const { name } = req.body;
      const userId = req.authUserId;

      if (!userId) {
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      if (!name || typeof name !== 'string' || name.trim() === '') {
        return res.status(400).json({
          success: false,
          error: 'Invalid name provided'
        });
      }

      // Bind username to userId using the new single-session logic
      await (server as any).bindUsernameToUserId(userId, name.trim());

      return res.json({
        success: true,
        message: 'Login name saved successfully',
        userId,
        name: name.trim()
      });
    } catch (error) {
      console.error('Error saving login name:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // GET endpoint to retrieve user login name
  app.get('/api/get-login-name', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userId = req.authUserId;

      if (!userId) {
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      const userNamesMap = (server as any).getUserNamesMap();
      const name = userNamesMap.get(userId);

      if (!name) {
        return res.json({
          success: true,
          name: null,
          message: 'No login name found for this user'
        });
      }

      return res.json({
        success: true,
        name,
        userId
      });
    } catch (error) {
      console.error('Error retrieving login name:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // GET endpoint to retrieve user settings
  app.get('/api/user-settings', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userId = req.authUserId;

      if (!userId) {
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      const username = (server as any).getUsername(userId);
      if (!username) {
        return res.json({
          success: true,
          settings: { ttsEnabled: true },
          message: 'No username found, returning default settings'
        });
      }

      const userMetadataService = (server as any).getUserMetadataService();
      const settings = userMetadataService.getUserSettings(username);

      // If no settings exist, return default with TTS enabled
      if (!settings) {
        const defaultSettings = { ttsEnabled: true };
        userMetadataService.setUserSettings(username, defaultSettings);
        return res.json({
          success: true,
          settings: defaultSettings
        });
      }

      return res.json({
        success: true,
        settings: settings
      });
    } catch (error) {
      console.error('Error retrieving user settings:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint to save user settings
  app.post('/api/user-settings', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const { ttsEnabled } = req.body;
      const userId = req.authUserId;

      if (!userId) {
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      const username = (server as any).getUsername(userId);
      if (!username) {
        return res.status(400).json({
          success: false,
          error: 'Username not found. Please log in first.'
        });
      }

      if (typeof ttsEnabled !== 'boolean') {
        return res.status(400).json({
          success: false,
          error: 'Invalid ttsEnabled value'
        });
      }

      const userMetadataService = (server as any).getUserMetadataService();
      userMetadataService.setUserSettings(username, { ttsEnabled });

      return res.json({
        success: true,
        message: 'User settings saved successfully',
        settings: { ttsEnabled }
      });
    } catch (error) {
      console.error('Error saving user settings:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint for agent replies (speaks text to user)
  app.post('/agent_reply', (async (req: express.Request, res: Response, next: NextFunction) => {
    try {
      const { username, text } = req.body;

      if (!username || typeof username !== 'string') {
        return res.status(400).json({
          success: false,
          error: 'Invalid username provided'
        });
      }

      if (!text || typeof text !== 'string') {
        return res.status(400).json({
          success: false,
          error: 'Invalid text provided'
        });
      }

      // Get userId for the username
      const userId = (server as any).getUserIdForUsername(username);
      if (!userId) {
        return res.status(404).json({
          success: false,
          error: 'User not found or not logged in'
        });
      }

      // Get the AudioFeedback instance for this user
      const audioFeedbackMap = (server as any).audioFeedbackMap;
      const audioFeedback = audioFeedbackMap?.get(userId);

      if (!audioFeedback) {
        return res.status(404).json({
          success: false,
          error: 'Audio feedback not available for this user'
        });
      }

      // Speak the text with high priority
      audioFeedback.speak(text, require('./services/AudioFeedback').FeedbackPriority.High);

      return res.json({
        success: true,
        message: 'Text spoken successfully'
      });
    } catch (error) {
      console.error('Error in /agent_reply:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint to stop stream and set user state to IDLE
  app.post('/api/stop-stream', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userId = req.authUserId;
      const timestamp = new Date().toISOString();

      if (!userId) {
        console.error(`[${timestamp}] [stop-stream] No userId found in request`);
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      console.log(`[${timestamp}] [stop-stream] Request from userId: ${userId}`);

      // Try to get username from request body first (most reliable), then fall back to server mapping
      let username = req.body.username;

      if (!username) {
        console.log(`[${timestamp}] [stop-stream] No username in request body, checking server mapping...`);
        username = (server as any).getUsername(userId);
      } else {
        console.log(`[${timestamp}] [stop-stream] Using username from request body: ${username}`);
      }

      if (!username) {
        console.warn(`[${timestamp}] [stop-stream] No username found for userId: ${userId}. This might indicate the session was already cleaned up or the user logged in from another device.`);

        // Even if we can't find the username, we should still try to stop the stream
        // and allow the redirect to happen
        const session = (server as any).userSessionsMap?.get(userId);
        if (session) {
          try {
            await session.camera.stopStream();
            console.log(`[${timestamp}] [stop-stream] Stream stopped for userId: ${userId} (no username mapping)`);
          } catch (streamError) {
            console.error(`[${timestamp}] [stop-stream] Error stopping stream:`, streamError);
          }
        }

        // Return success even without username to allow UI navigation
        return res.json({
          success: true,
          message: 'Stream stopped (session may have expired)',
          warning: 'Username mapping not found'
        });
      }

      console.log(`[${timestamp}] [stop-stream] Username: ${username}`);

      // Clear active procedure
      (server as any).clearActiveProcedure(username);

      // Set user state to IDLE
      await (server as any).setUserState(username, 'IDLE');

      // Call v2 API to stop the procedure on the backend
      try {
        const externalApiUrl = 'https://oneshotcopilot.ngrok.dev';
        const stopResponse = await fetch(`${externalApiUrl}/stop_procedure`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ camera_id: username }),
        });

        if (!stopResponse.ok) {
          console.error(`[${timestamp}] [stop-stream] Failed to stop procedure on external API: ${stopResponse.status}`);
        } else {
          console.log(`[${timestamp}] [stop-stream] Successfully stopped procedure on external API for ${username}`);
        }
      } catch (apiError) {
        console.error(`[${timestamp}] [stop-stream] Error calling external stop API:`, apiError);
      }

      // Stop the camera stream
      const session = (server as any).userSessionsMap?.get(userId);
      if (session) {
        try {
          await session.camera.stopStream();
          console.log(`[${timestamp}] [stop-stream] Stream stopped for ${username}`);
        } catch (streamError) {
          console.error(`[${timestamp}] [stop-stream] Error stopping stream:`, streamError);
        }
      }

      return res.json({
        success: true,
        message: 'Stream stopped successfully'
      });
    } catch (error) {
      const timestamp = new Date().toISOString();
      console.error(`[${timestamp}] [stop-stream] Error:`, error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // GET endpoint to fetch procedure data from external API
  app.get('/api/procedure', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const username = req.query.username as string;

      if (!username) {
        return res.status(400).json({
          success: false,
          error: 'Username is required'
        });
      }

      // Fetch from external API
      const externalApiUrl = 'https://oneshotcopilot.ngrok.dev';
      const response = await fetch(`${externalApiUrl}/api/procedure?username=${username}`);

      if (!response.ok) {
        console.error(`[${new Date().toISOString()}] Failed to fetch procedure from external API: ${response.status}`);
        return res.status(response.status).json({
          success: false,
          error: 'Failed to fetch procedure'
        });
      }

      const data = await response.json();
      return res.json(data);
    } catch (error) {
      console.error('Error fetching procedure:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // GET endpoint to proxy v2 status API
  app.get('/api/v2/status', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const cameraId = req.query.camera_id as string;

      if (!cameraId) {
        return res.status(400).json({
          success: false,
          error: 'camera_id is required'
        });
      }

      // Proxy to external API
      const externalApiUrl = 'https://oneshotcopilot.ngrok.dev';
      const response = await fetch(`${externalApiUrl}/api/v2/status?camera_id=${encodeURIComponent(cameraId)}`);

      if (!response.ok) {
        console.error(`[${new Date().toISOString()}] Failed to fetch v2 status from external API: ${response.status}`);
        return res.status(response.status).json({
          success: false,
          error: 'Failed to fetch status'
        });
      }

      const data = await response.json();
      return res.json(data);
    } catch (error) {
      console.error('Error fetching v2 status:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint to start a stream (set user state to WORKING and announce via TTS)
  app.post('/api/start-stream', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const { procedure } = req.body;
      const userId = req.authUserId;

      if (!userId) {
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      if (!procedure || typeof procedure !== 'string') {
        return res.status(400).json({
          success: false,
          error: 'Invalid procedure provided'
        });
      }

      const username = (server as any).getUsername(userId);
      if (!username) {
        return res.status(400).json({
          success: false,
          error: 'Username not found. Please log in first.'
        });
      }

      // RTMP camera streaming disabled - keeping only external API integration
      /*
      // Start the camera stream
      const session = (server as any).getSession(username);
      if (session && session.camera) {
        try {
          // Check for existing stream before starting
          const existingStream = await session.camera.checkExistingStream();
          if (existingStream.hasActiveStream && existingStream.streamInfo?.type === 'unmanaged') {
            console.log(`[${new Date().toISOString()}] Found existing stream for ${username}, stopping it first...`);
            try {
              await session.camera.stopStream();
              console.log(`[${new Date().toISOString()}] Existing stream stopped for ${username}`);
            } catch (error) {
              console.error(`[${new Date().toISOString()}] Error stopping existing stream:`, error);
              // Continue anyway - we'll try to start the new stream
            }
          }

          await session.camera.startStream({
            rtmpUrl: process.env.RTMP_URL || 'rtmp://YOUR_IP/live/stream',
            //rtmpUrl: "rtmp://192.168.9.21:1935/live/oneshot"
          });
          console.log(`[${new Date().toISOString()}] Camera stream started successfully for ${username}`);
        } catch (error) {
          console.error(`[${new Date().toISOString()}] Error starting camera stream:`, error);
          return res.status(500).json({
            success: false,
            error: 'Failed to start camera stream'
          });
        }
      } else {
        console.warn(`[${new Date().toISOString()}] No session or camera found for user: ${username}`);
        return res.status(400).json({
          success: false,
          error: 'Session not found. Please reconnect.'
        });
      }
      */

      // Make POST request to backend API v2 for starting procedure
      try {
        const backendUrl = 'https://oneshotcopilot.ngrok.dev/api/v2/procedures/start';
        console.log(`[${new Date().toISOString()}] Making POST request to backend API v2 for procedure "${procedure}": ${backendUrl}`);

        const backendResponse = await fetch(backendUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            username: username,
            procedure_id: procedure,
            source_id: username,
            policy: 'replace'
          })
        });

        if (backendResponse.ok) {
          console.log(`[${new Date().toISOString()}] Successfully started procedure via API v2 for ${username} - Procedure: ${procedure}`);
        } else {
          console.error(`[${new Date().toISOString()}] Backend API v2 returned error status: ${backendResponse.status}`);
        }
      } catch (backendError) {
        // Log the error but don't fail the request
        console.error(`[${new Date().toISOString()}] Error starting procedure via API v2:`, backendError);
      }

      // Set user state to WORKING
      await (server as any).setUserState(username, 'WORKING');
      (server as any).setActiveProcedure(username, procedure);

      // Check if TTS is enabled and speak the procedure start message
      const userMetadataService = (server as any).getUserMetadataService();
      const settings = userMetadataService.getUserSettings(username);

      if (settings?.ttsEnabled) {
        const audioFeedbackMap = (server as any).audioFeedbackMap;
        const audioFeedback = audioFeedbackMap.get(userId);
        if (audioFeedback) {
          const message = `${procedure} started`;
          audioFeedback.speak(message, require('./services/AudioFeedback').FeedbackPriority.High);
        }
      }

      return res.json({
        success: true,
        message: 'Stream started',
        procedure: procedure,
        username: username
      });
    } catch (error) {
      console.error('Error starting stream:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint to stop a stream (set user state to IDLE)
  app.post('/api/stop-stream', (async (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    try {
      const userId = req.authUserId;

      if (!userId) {
        return res.status(401).json({
          success: false,
          error: 'User not authenticated'
        });
      }

      const username = (server as any).getUsername(userId);
      if (!username) {
        return res.status(400).json({
          success: false,
          error: 'Username not found. Please log in first.'
        });
      }

      // Get the active procedure before clearing it
      const activeProcedure = (server as any).getActiveProcedure(username);

      // Call v2 API to stop the procedure on the backend
      if (activeProcedure) {
        try {
          const backendUrl = 'https://oneshotcopilot.ngrok.dev/api/v2/procedures/stop';
          console.log(`[${new Date().toISOString()}] Making POST request to backend API v2 to stop procedure "${activeProcedure}": ${backendUrl}`);

          const backendResponse = await fetch(backendUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              username: username,
              procedure_id: activeProcedure,
              source_id: username,
              policy: 'replace'
            })
          });

          if (backendResponse.ok) {
            console.log(`[${new Date().toISOString()}] Successfully stopped procedure via API v2 for ${username} - Procedure: ${activeProcedure}`);
          } else {
            console.error(`[${new Date().toISOString()}] Backend API v2 returned error status when stopping: ${backendResponse.status}`);
          }
        } catch (backendError) {
          // Log the error but don't fail the stream stop
          console.error(`[${new Date().toISOString()}] Error stopping procedure via API v2:`, backendError);
        }
      }

      // RTMP camera streaming disabled
      /*
      // Stop the camera stream
      const session = (server as any).getSession(username);
      if (session && session.camera) {
        try {
          await session.camera.stopStream();
          console.log(`[${new Date().toISOString()}] Camera stream stopped for user: ${username}`);
        } catch (error) {
          console.error(`[${new Date().toISOString()}] Error stopping camera stream:`, error);
          // Continue with state cleanup even if stream stop fails
        }
      }
      */

      // Set user state to IDLE
      (server as any).clearActiveProcedure(username);
      await (server as any).setUserState(username, 'IDLE');

      return res.json({
        success: true,
        message: 'Stream stopped',
        username: username
      });
    } catch (error) {
      console.error('Error stopping stream:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint for step progression (no audio feedback)
  app.post('/progress_step', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] [PROGRESS_STEP] Request received`);

    try {
      const { username, text, from_step, to_step } = req.body;
      console.log(`[${timestamp}] [PROGRESS_STEP] username="${username}", text="${text}", from_step=${from_step}, to_step=${to_step}`);

      if (!username || typeof username !== 'string') {
        return res.status(400).json({
          success: false,
          error: 'Invalid username provided'
        });
      }

      // Note: TTS is intentionally disabled for progress_step
      // Step announcements are handled by /on_step endpoint instead

      return res.json({
        success: true,
        message: 'Progress notification received',
        username: username,
        from_step: from_step,
        to_step: to_step
      });
    } catch (error) {
      console.error(`[${timestamp}] [PROGRESS_STEP] Error:`, error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);

  // POST endpoint for step notifications with audio feedback
  app.post('/on_step', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    const timestamp = new Date().toISOString();
    console.log(`[${timestamp}] [ON_STEP] Request received`);

    try {
      const { username, text } = req.body;
      console.log(`[${timestamp}] [ON_STEP] Body: username="${username}", text="${text}"`);

      if (!username || typeof username !== 'string') {
        console.warn(`[${timestamp}] [ON_STEP] Invalid username: ${username}`);
        return res.status(400).json({
          success: false,
          error: 'Invalid username provided'
        });
      }

      if (!text || typeof text !== 'string') {
        console.warn(`[${timestamp}] [ON_STEP] Invalid text: ${text}`);
        return res.status(400).json({
          success: false,
          error: 'Invalid text provided'
        });
      }

      // Check for duplicate TTS request
      const now = Date.now();
      const recent = recentTTSRequests.get(username);
      if (recent && recent.text === text && (now - recent.timestamp) < TTS_DUPLICATE_WINDOW_MS) {
        console.log(`[${timestamp}] [ON_STEP] Duplicate TTS request detected within ${TTS_DUPLICATE_WINDOW_MS}ms, skipping - username="${username}", text="${text}"`);
        return res.json({
          success: true,
          message: 'Duplicate request skipped',
          username: username,
          text: text,
          ttsEnabled: true
        });
      }

      // Get userId for the username
      const userId = (server as any).getUserIdForUsername(username);
      console.log(`[${timestamp}] [ON_STEP] Username "${username}" maps to userId: ${userId || 'NOT_FOUND'}`);

      if (!userId) {
        console.warn(`[${timestamp}] [ON_STEP] User "${username}" not found or not logged in`);
        return res.status(404).json({
          success: false,
          error: 'User not found or not logged in'
        });
      }

      // Check if TTS is enabled for this user
      const userMetadataService = (server as any).getUserMetadataService();
      const settings = userMetadataService.getUserSettings(username);
      console.log(`[${timestamp}] [ON_STEP] TTS enabled for "${username}": ${settings?.ttsEnabled ?? false}`);

      if (settings?.ttsEnabled) {
        // Store this request to detect duplicates
        recentTTSRequests.set(username, { text, timestamp: now });

        // Clean up old entries (keep map from growing indefinitely)
        if (recentTTSRequests.size > 100) {
          const oldestAllowed = now - TTS_DUPLICATE_WINDOW_MS;
          for (const [key, value] of recentTTSRequests.entries()) {
            if (value.timestamp < oldestAllowed) {
              recentTTSRequests.delete(key);
            }
          }
        }

        // Get AudioFeedback instance for this user
        const audioFeedbackMap = (server as any).audioFeedbackMap;
        const audioFeedback = audioFeedbackMap.get(userId);
        console.log(`[${timestamp}] [ON_STEP] AudioFeedback instance found: ${!!audioFeedback}`);

        if (!audioFeedback) {
          console.error(`[${timestamp}] [ON_STEP] Audio feedback service not available for userId: ${userId}`);
          return res.status(404).json({
            success: false,
            error: 'Audio feedback service not available for this user'
          });
        }

        // Speak the text using high priority
        console.log(`[${timestamp}] [ON_STEP] Speaking text with HIGH priority: "${text}"`);
        audioFeedback.speak(text, require('./services/AudioFeedback').FeedbackPriority.High);
        console.log(`[${timestamp}] [ON_STEP] TTS request sent successfully`);
      } else {
        console.log(`[${timestamp}] [ON_STEP] TTS disabled for user "${username}", skipping speech`);
      }

      console.log(`[${timestamp}] [ON_STEP] Success response sent`);
      return res.json({
        success: true,
        message: 'Step notification received',
        username: username,
        text: text,
        ttsEnabled: settings?.ttsEnabled ?? false
      });
    } catch (error) {
      console.error(`[${timestamp}] [ON_STEP] Error:`, error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);
}