import { AuthenticatedRequest, AppServer } from '@mentra/sdk';
import express, { Response, NextFunction } from 'express';
import path from 'path';

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

          // Make POST request to backend for all procedures
          try {
            // Map frontend procedure names to backend procedure_ids
            let procedureId: string;
            const procedureLower = procedure.toLowerCase();
            
            if (procedureLower === 'pepperoni pizza') {
              procedureId = 'pizza_custom@v1';
            } else if (procedure === 'debug_objects_gestures@v1') {
              // This procedure doesn't exist yet - use candy_veg_detection as fallback
              procedureId = 'candy_veg_detection@v1';
            } else if (procedure === 'starting:detect_office_items') {
              // Backend expects "Detect Office Items" with capitals and spaces
              procedureId = 'Detect Office Items';
            } else {
              // For any other procedure, use it as-is
              procedureId = procedure;
            }
            
            const backendUrl = `https://oneshotcopilot.ngrok.dev/api/start_procedure?username=${encodeURIComponent(username)}&procedure_id=${encodeURIComponent(procedureId)}`;
            console.log(`[${new Date().toISOString()}] Making POST request to backend for procedure "${procedure}" (ID: ${procedureId}): ${backendUrl}`);
            
            const backendResponse = await fetch(backendUrl, {
              method: 'POST'
            });

            if (backendResponse.ok) {
              console.log(`[${new Date().toISOString()}] Successfully notified backend of procedure start for ${username} - Procedure: ${procedure} (ID: ${procedureId})`);
            } else {
              console.error(`[${new Date().toISOString()}] Backend returned error status: ${backendResponse.status}`);
            }
          } catch (backendError) {
            // Log the error but don't fail the stream start
            console.error(`[${new Date().toISOString()}] Error notifying backend of procedure start:`, backendError);
          }
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

  // POST endpoint for step progression with audio feedback
  app.post('/progress_step', ((req: AuthenticatedRequest, res: Response, next: NextFunction) => {
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

      // Get AudioFeedback instance for this user
      const audioFeedbackMap = (server as any).audioFeedbackMap;
      const audioFeedback = audioFeedbackMap.get(userId);

      if (!audioFeedback) {
        return res.status(404).json({
          success: false,
          error: 'Audio feedback service not available for this user'
        });
      }

      // Speak the text using the AudioFeedback service
      audioFeedback.speak(text, require('./services/AudioFeedback').FeedbackPriority.Low);

      return res.json({
        success: true,
        message: 'Audio feedback sent',
        username: username,
        text: text
      });
    } catch (error) {
      console.error('Error in progress_step endpoint:', error);
      return res.status(500).json({
        success: false,
        error: 'Internal server error'
      });
    }
  }) as any);
}