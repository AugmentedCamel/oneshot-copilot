import dotenv from 'dotenv';
dotenv.config();
import { ToolCall, AppServer, AppSession, StreamType } from '@mentra/sdk';
import path from 'path';
import { setupExpressRoutes } from './webview';
import { handleToolCall } from './tools';
import { AudioFeedback, FeedbackPriority } from './services/AudioFeedback';
import { UserMetadataService } from './services/UserMetadataService';

const PACKAGE_NAME = process.env.PACKAGE_NAME ?? (() => { throw new Error('PACKAGE_NAME is not set in .env file'); })();
const MENTRAOS_API_KEY = process.env.MENTRAOS_API_KEY ?? (() => { throw new Error('MENTRAOS_API_KEY is not set in .env file'); })();
const PORT = parseInt(process.env.PORT || '3000');
//const PORT = '3000';

/** User state enum */
export enum UserState {
    OFFLINE = 'OFFLINE',
    IDLE = 'IDLE',
    WORKING = 'WORKING'
}

class AmICookedApp extends AppServer {
  constructor() {
    super({
      packageName: PACKAGE_NAME,
      apiKey: MENTRAOS_API_KEY,
      port: PORT,
      publicDir: path.join(__dirname, '../public'),
    });

    // Set up Express routes
    setupExpressRoutes(this);
  }

  /** Map to store active user sessions */
  private userSessionsMap = new Map<string, AppSession>();

  /** Map to store user login names (userId -> username) */
  private userNamesMap = new Map<string, string>();

  /** Reverse map to track which userId currently owns each username (username -> userId) */
  private usernameToUserIdMap = new Map<string, string>();

  /** Public map to track user states by username (OFFLINE, IDLE, or WORKING) */
  public userStates = new Map<string, UserState>();
  /** Map to track active procedures by username (username -> procedure name) */
  private activeProcedures = new Map<string, string>();

  /** Map to store AudioFeedback instances per userId */
  private audioFeedbackMap = new Map<string, AudioFeedback>();

  /** Service to manage user metadata and settings */
  private userMetadataService = new UserMetadataService();

  /**
   * Gets the user names map
   * @returns The map of userId to login names
   */
  public getUserNamesMap(): Map<string, string> {
    return this.userNamesMap;
  }

  /**
   * Gets the user metadata service
   * @returns The UserMetadataService instance
   */
  public getUserMetadataService(): UserMetadataService {
    return this.userMetadataService;
  }

  /**
   * Gets the username for a given userId
   * @param userId - The user ID
   * @returns The username or undefined if not found
   */
  public getUsername(userId: string): string | undefined {
    return this.userNamesMap.get(userId);
  }

  /**
   * Gets the current state of a user by username
   * @param username - The username
   * @returns The user's current state (defaults to OFFLINE if not set)
   */
  public getUserState(username: string): UserState {
    return this.userStates.get(username) ?? UserState.OFFLINE;
  }

  /**
   * Gets the userId currently associated with a username
   * @param username - The username
   * @returns The userId or undefined if no active session
   */
  public getUserIdForUsername(username: string): string | undefined {
    return this.usernameToUserIdMap.get(username);
  }
  /**
   * Gets the session for a user by username
   * @param username - The username
   * @returns The AppSession or undefined if not found
   */
  public getSession(username: string): AppSession | undefined {
    const userId = this.getUserIdForUsername(username);
    return userId ? this.userSessionsMap.get(userId) : undefined;
  }

  /**
   * Sets the active procedure for a user
   * @param username - The username
   * @param procedure - The procedure name
   */
  public setActiveProcedure(username: string, procedure: string): void {
    this.activeProcedures.set(username, procedure);
    console.log(`[${new Date().toISOString()}] Active procedure set for ${username}: ${procedure}`);
  }

  /**
   * Gets the active procedure for a user
   * @param username - The username
   * @returns The procedure name or undefined if not found
   */
  public getActiveProcedure(username: string): string | undefined {
    return this.activeProcedures.get(username);
  }

  /**
   * Clears the active procedure for a user
   * @param username - The username
   */
  public clearActiveProcedure(username: string): void {
    const hadProcedure = this.activeProcedures.has(username);
    this.activeProcedures.delete(username);
    if (hadProcedure) {
      console.log(`[${new Date().toISOString()}] Active procedure cleared for ${username}`);
    }
  }

  /**
   * Sets the state of a user by username
   * @param username - The username
   * @param state - The new state (OFFLINE, IDLE, or WORKING)
   */
  public async setUserState(username: string, state: UserState): Promise<void> {
    const previousState = this.userStates.get(username);
    this.userStates.set(username, state);

    // Log state changes
    if (previousState !== state) {
      console.log(`[UserState] ${username}: ${previousState || 'undefined'} -> ${state}`);

      // Check if user has TTS enabled
      const userSettings = this.userMetadataService.getUserSettings(username);
      if (userSettings?.ttsEnabled) {
        // Get the userId for this username to access their session
        const userId = this.getUserIdForUsername(username);
        if (userId) {
          const audioFeedback = this.audioFeedbackMap.get(userId);

          // Speak feedback for IDLE state transitions
          if (state === UserState.IDLE && previousState === UserState.WORKING) {
            audioFeedback?.speak('task done', FeedbackPriority.High);
          }
          // Note: WORKING state TTS is handled by the /api/start-stream endpoint
          // with specific procedure name, so we don't announce it here
        }
      }
    }
  }

  /**
   * Gets state by userId (convenience method that looks up username first)
   * @param userId - The user ID
   * @returns The user's current state (defaults to OFFLINE if not set)
   */
  public getUserStateByUserId(userId: string): UserState {
    const username = this.getUsername(userId);
    return username ? this.getUserState(username) : UserState.OFFLINE;
  }

  /**
   * Sets state by userId (convenience method that looks up username first)
   * @param userId - The user ID
   * @param state - The new state (IDLE or WORKING)
   */
  public async setUserStateByUserId(userId: string, state: UserState): Promise<void> {
    const username = this.getUsername(userId);
    if (username) {
      await this.setUserState(username, state);
    }
  }

  /**
   * Checks if a user is currently offline (by username)
   * @param username - The username
   * @returns true if user is OFFLINE, false otherwise
   */
  public isUserOffline(username: string): boolean {
    return this.getUserState(username) === UserState.OFFLINE;
  }

  /**
   * Checks if a user is currently idle (by username)
   * @param username - The username
   * @returns true if user is IDLE, false otherwise
   */
  public isUserIdle(username: string): boolean {
    return this.getUserState(username) === UserState.IDLE;
  }

  /**
   * Checks if a user is currently working (by username)
   * @param username - The username
   * @returns true if user is WORKING, false otherwise
   */
  public isUserWorking(username: string): boolean {
    return this.getUserState(username) === UserState.WORKING;
  }

  /**
   * Handles tool calls from the MentraOS system
   * @param toolCall - The tool call request
   * @returns Promise resolving to the tool call response or undefined
   */
  protected async onToolCall(toolCall: ToolCall): Promise<string | undefined> {
    return handleToolCall(toolCall, toolCall.userId, this.userSessionsMap.get(toolCall.userId));
  }

  /**
   * Handles new user sessions
   * Sets up event listeners and displays welcome message
   * @param session - The app session instance
   * @param sessionId - Unique session identifier
   * @param userId - User identifier
   */
  /**
   * Binds a username to a userId, implementing single-session-per-username logic
   * @param userId - The user ID to bind
   * @param username - The username to bind
   */
  public async bindUsernameToUserId(userId: string, username: string): Promise<void> {
    // Check if this username is already bound to a different userId
    const existingUserId = this.usernameToUserIdMap.get(username);

    if (existingUserId && existingUserId !== userId) {
      // Uncouple the previous device's session from this username
      this.userNamesMap.delete(existingUserId);
    }

    // Bind the username to this userId
    this.userNamesMap.set(userId, username);
    this.usernameToUserIdMap.set(username, userId);

    // Set user state to IDLE when they log in
    await this.setUserState(username, UserState.IDLE);
  }

  protected async onSession(session: AppSession, sessionId: string, userId: string): Promise<void> {
    this.userSessionsMap.set(userId, session);
    console.log('on session started');

    console.log(
      `[${new Date().toISOString()}] [RTMP] Setting up stream status listener for userId: ${userId}`,
    );

    this.audioFeedbackMap.get(userId)?.speak('welcome', FeedbackPriority.High);
    const r = await session.camera.checkExistingStream();

    if (r.hasActiveStream && r.streamInfo?.type === 'unmanaged') {
      console.warn('Clearing stale unmanaged stream at', r.streamInfo?.rtmpUrl);
      try {
        await session.camera.stopStream();
      } catch {}
    }

    // Creates AudioFeedback instance for this user
    this.audioFeedbackMap.set(userId, new AudioFeedback(session, console));
    // Add cleanup handler to stop the stream when session ends
    this.addCleanupHandler(() => {
      try {
        session.camera.stopStream();
        console.log(`[${new Date().toISOString()}] Stream stopped for userId: ${userId}`);
      } catch (error) {
        console.error(
          `[${new Date().toISOString()}] Error stopping stream for userId: ${userId}`,
          error,
        );
      }
    });
  }

  /**
   * Handles session stop events
   * @param userId - User identifier (actually sessionId in the SDK)
   * @param sessionId - Session identifier
   * @param reason - Reason for stopping
   */
  protected async onStop(userId: string, sessionId: string, reason: string): Promise<void> {
    console.log(`[onStop] Session stopping for sessionId: ${userId}, reason: ${reason}`);

    // Extract actual userId from sessionId (format: userId-packageName)
    const actualUserId = userId.split('-' + PACKAGE_NAME)[0];
    console.log(`[onStop] Extracted userId: ${actualUserId}`);

    // Get the username before deletion
    const username = this.getUsername(actualUserId);
    console.log(`[onStop] Found username: ${username || 'none'}`);

    // Clean up AudioFeedback instance
    const audioFeedback = this.audioFeedbackMap.get(actualUserId);
    if (audioFeedback) {
      audioFeedback.dispose();
      this.audioFeedbackMap.delete(actualUserId);
    }

    // Remove the userId from the session map
    this.userSessionsMap.delete(actualUserId);

    // If this session has a username, mark it OFFLINE
    if (username) {
      console.log(`[onStop] Setting ${username} to OFFLINE`);
      await this.setUserState(username, UserState.OFFLINE);
      this.usernameToUserIdMap.delete(username);
    } else {
      console.log(
        `[onStop] No username found for userId ${actualUserId}, skipping OFFLINE transition`,
      );
    }

    // Clear active procedure if it exists
    if (username) {
      this.clearActiveProcedure(username);
    }
    // Uncouple the userId from the username mapping
    this.userNamesMap.delete(actualUserId);
  }
}

// Start the server
const app = new AmICookedApp();

app.start().catch(console.error);