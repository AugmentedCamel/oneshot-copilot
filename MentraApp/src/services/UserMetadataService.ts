export interface UserSettings {
  ttsEnabled: boolean;
}

export class UserMetadataService {
  private userMetadataStore: Map<string, UserSettings>;

  constructor() {
    this.userMetadataStore = new Map<string, UserSettings>();
  }

  /**
   * Set or update user settings for a specific username
   * @param username - The username to store settings for
   * @param settings - The user settings object
   */
  setUserSettings(username: string, settings: UserSettings): void {
    this.userMetadataStore.set(username, settings);
  }

  /**
   * Get user settings for a specific username as JSON string
   * @param username - The username to retrieve settings for
   * @returns JSON string of user settings, or null if not found
   */
  getUserSettingsAsJson(username: string): string | null {
    const settings = this.userMetadataStore.get(username);
    return settings ? JSON.stringify(settings) : null;
  }

  /**
   * Get user settings object for a specific username
   * @param username - The username to retrieve settings for
   * @returns UserSettings object or undefined if not found
   */
  getUserSettings(username: string): UserSettings | undefined {
    return this.userMetadataStore.get(username);
  }

  /**
   * Get all user settings as JSON string
   * @returns JSON string containing all user settings mapped by username
   */
  getAllUserSettingsAsJson(): string {
    const allSettings: Record<string, UserSettings> = {};
    this.userMetadataStore.forEach((settings, username) => {
      allSettings[username] = settings;
    });
    return JSON.stringify(allSettings);
  }

  /**
   * Check if settings exist for a username
   * @param username - The username to check
   * @returns true if settings exist, false otherwise
   */
  hasUserSettings(username: string): boolean {
    return this.userMetadataStore.has(username);
  }

  /**
   * Delete user settings for a specific username
   * @param username - The username to delete settings for
   * @returns true if settings were deleted, false if not found
   */
  deleteUserSettings(username: string): boolean {
    return this.userMetadataStore.delete(username);
  }
}