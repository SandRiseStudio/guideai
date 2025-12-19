/**
 * LoginPage Component
 *
 * Authentication page supporting both device flow (humans) and
 * client credentials (agents).
 *
 * Features:
 * - Device flow with user code display and QR code
 * - Client credentials form for service accounts
 * - Spring-physics animations (60fps)
 * - WCAG AA compliant
 * - Keyboard navigation support
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_prototype_consent_ux (Teacher)
 * - COLLAB_SAAS_REQUIREMENTS.md animation specs
 */

import { useState, useEffect, useCallback, type FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { authStore, AUTH_STORE_INSTANCE_ID } from '../stores/authStore';
import './LoginPage.css';

type LoginMode = 'select' | 'device-flow' | 'client-credentials';

interface LocationState {
  from?: string;
}

function createOAuthState(provider: 'github' | 'google'): string {
  const nonce = typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const payload = JSON.stringify({ provider, nonce, ts: Date.now() });
  const encoded = btoa(payload);
  return encoded.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

/**
 * Copy text to clipboard with fallback for older browsers.
 */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    // Fallback for older browsers
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    return true;
  } catch {
    return false;
  }
}

/**
 * Format seconds into mm:ss display.
 */
function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    isAuthenticated,
    startLogin,
    cancelLogin,
    loginWithClientCredentials,
    error: authError,
    deviceFlowStatus,
    deviceCode,
  } = useAuth();

  // Subscribe directly to the store for device-flow fields.
  // This avoids any potential stale context propagation during Vite HMR/fast-refresh.
  // const { deviceFlow } = useDeviceFlow();
  // const deviceFlowStatus = deviceFlow.status;
  // const deviceCode = deviceFlow.deviceCode;

  const [mode, setMode] = useState<LoginMode>('select');
  const [copied, setCopied] = useState(false);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [credentialsError, setCredentialsError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Get redirect destination from location state
  const from = (location.state as LocationState)?.from ?? '/';

  // Calculate remaining time for device flow
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  // Dev-only: help diagnose why user_code / verification_uri aren't rendering
  useEffect(() => {
    if (import.meta.env.DEV) {
      console.log('[LoginPage] AUTH_STORE_INSTANCE_ID', AUTH_STORE_INSTANCE_ID);
      console.log('[LoginPage] device flow state', { deviceFlowStatus, deviceCode });
      console.log('[LoginPage] authStore.getState().deviceFlow', authStore.getState().deviceFlow);
    }
  }, [deviceFlowStatus, deviceCode]);

  // Update countdown timer based on deviceCode expiry
  useEffect(() => {
    if (deviceCode?.expiresIn) {
      // Estimate expiry time based on when we got the code
      const expiresAt = Date.now() + (deviceCode.expiresIn * 1000);
      const updateTimer = () => {
        const remaining = Math.max(0, Math.floor((expiresAt - Date.now()) / 1000));
        setTimeRemaining(remaining);
      };

      updateTimer();
      const interval = setInterval(updateTimer, 1000);
      return () => clearInterval(interval);
    }
    return undefined;
  }, [deviceCode?.expiresIn]);

  // Handle device flow start
  const handleStartDeviceFlow = useCallback(async () => {
    setMode('device-flow');
    await startLogin();
  }, [startLogin]);

  // Handle copy user code
  const handleCopyCode = useCallback(async () => {
    if (deviceCode?.userCode) {
      const success = await copyToClipboard(deviceCode.userCode);
      if (success) {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    }
  }, [deviceCode?.userCode]);

  // Handle cancel
  const handleCancel = useCallback(() => {
    cancelLogin();
    setMode('select');
  }, [cancelLogin]);

  // Handle client credentials submission
  const handleCredentialsSubmit = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    setCredentialsError(null);
    setIsSubmitting(true);

    try {
      await loginWithClientCredentials(clientId, clientSecret);
      navigate(from, { replace: true });
    } catch (err) {
      setCredentialsError(
        err instanceof Error ? err.message : 'Authentication failed'
      );
    } finally {
      setIsSubmitting(false);
    }
  }, [clientId, clientSecret, loginWithClientCredentials, navigate, from]);

  // Handle social login (OAuth redirect)
  const handleSocialLogin = useCallback((provider: 'github' | 'google') => {
    // Build OAuth authorization URL
    const redirectUri = `${window.location.origin}/auth/callback`;
    const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
    const apiBaseUrl = rawBaseUrl.endsWith('/api') ? rawBaseUrl : `${rawBaseUrl}/api`;
    const state = createOAuthState(provider);
    const authUrl = `${apiBaseUrl}/v1/auth/oauth/${provider}/authorize?redirect_uri=${encodeURIComponent(redirectUri)}&state=${encodeURIComponent(state)}`;

    // Redirect to OAuth provider
    window.location.href = authUrl;
  }, []);

  // Keyboard shortcut to copy code
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (mode === 'device-flow' && (e.metaKey || e.ctrlKey) && e.key === 'c') {
        if (document.getSelection()?.toString() === '') {
          handleCopyCode();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [mode, handleCopyCode]);

  return (
    <div className="login-page">
      <div className="login-container animate-scale-in">
        {/* Logo and branding */}
        <header className="login-header">
          <div className="login-logo">
            <span className="login-logo-icon">🤖</span>
            <span className="login-logo-text">GuideAI</span>
          </div>
          <h1 className="login-title">Welcome back</h1>
          <p className="login-subtitle">Sign in to continue to your workspace</p>
        </header>

        {/* Mode Selection */}
        {mode === 'select' && (
          <div className="login-mode-select animate-fade-in-up">
            <button
              type="button"
              className="login-mode-button login-mode-human"
              onClick={handleStartDeviceFlow}
            >
              <span className="login-mode-icon">👤</span>
              <span className="login-mode-label">
                <strong>Sign in as Human</strong>
                <span>Use your browser to authenticate</span>
              </span>
              <span className="login-mode-arrow">→</span>
            </button>

            <button
              type="button"
              className="login-mode-button login-mode-agent"
              onClick={() => setMode('client-credentials')}
            >
              <span className="login-mode-icon">🤖</span>
              <span className="login-mode-label">
                <strong>Sign in as Agent</strong>
                <span>Use client credentials</span>
              </span>
              <span className="login-mode-arrow">→</span>
            </button>

            <div className="login-separator">
              <span>or continue with</span>
            </div>

            <div className="login-social-buttons">
              <button
                type="button"
                className="login-social-button login-social-github"
                onClick={() => handleSocialLogin('github')}
              >
                <svg className="login-social-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                </svg>
                <span>GitHub</span>
              </button>

              <button
                type="button"
                className="login-social-button login-social-google"
                onClick={() => handleSocialLogin('google')}
              >
                <svg className="login-social-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                <span>Google</span>
              </button>
            </div>

            <a href="/docs/api/authentication" className="login-help-link">
              Need help getting credentials?
            </a>
          </div>
        )}

        {/* Device Flow */}
        {mode === 'device-flow' && (
          <div className="login-device-flow animate-fade-in-up">
            {/* Pending - waiting for user to start flow */}
            {deviceFlowStatus === 'pending' && !deviceCode && (
              <div className="login-polling">
                <div className="login-status-spinner large" aria-hidden="true" />
                <p>Starting authentication...</p>
              </div>
            )}

            {/* Have device code - show it to user */}
            {deviceCode && (deviceFlowStatus === 'pending' || deviceFlowStatus === 'polling') && (
              <>
                <div className="login-instructions">
                  <p>
                    Visit{' '}
                    <a
                      href={deviceCode.verificationUri}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="login-verification-link"
                    >
                      {deviceCode.verificationUri}
                    </a>
                    {' '}and enter this code:
                  </p>
                </div>

                <button
                  type="button"
                  className="login-code-display"
                  onClick={handleCopyCode}
                  aria-label={`Copy code ${deviceCode.userCode}`}
                >
                  <span className="login-code-value">
                    {deviceCode.userCode}
                  </span>
                  <span className="login-code-hint">
                    {copied ? '✓ Copied!' : 'Click to copy'}
                  </span>
                </button>

                {/* QR Code placeholder - would use a QR library in production */}
                {deviceCode.verificationUriComplete && (
                  <div className="login-qr-section">
                    <p className="login-qr-label">Or scan this QR code:</p>
                    <div className="login-qr-placeholder" role="img" aria-label="QR code">
                      {/* In production, render actual QR code here */}
                      <span>📱</span>
                    </div>
                  </div>
                )}

                <div className="login-status">
                  <div className="login-status-spinner" aria-hidden="true" />
                  <span>Waiting for authorization...</span>
                </div>

                {timeRemaining !== null && timeRemaining > 0 && (
                  <p className="login-timer">
                    Code expires in {formatTime(timeRemaining)}
                  </p>
                )}

                {timeRemaining === 0 && (
                  <div className="login-expired">
                    <p>Code expired</p>
                    <button
                      type="button"
                      className="login-retry-button"
                      onClick={handleStartDeviceFlow}
                    >
                      Get new code
                    </button>
                  </div>
                )}
              </>
            )}

            {deviceFlowStatus === 'expired' && (
              <div className="login-error" role="alert">
                <span className="login-error-icon">⏱️</span>
                <p>Device code expired. Please try again.</p>
                <button
                  type="button"
                  className="login-retry-button"
                  onClick={handleStartDeviceFlow}
                >
                  Get new code
                </button>
              </div>
            )}

            {deviceFlowStatus === 'denied' && (
              <div className="login-error" role="alert">
                <span className="login-error-icon">🚫</span>
                <p>Authorization was denied.</p>
                <button
                  type="button"
                  className="login-retry-button"
                  onClick={handleStartDeviceFlow}
                >
                  Try again
                </button>
              </div>
            )}

            {deviceFlowStatus === 'error' && (
              <div className="login-error" role="alert">
                <span className="login-error-icon">⚠️</span>
                <p>{authError ?? 'Authentication failed'}</p>
                <button
                  type="button"
                  className="login-retry-button"
                  onClick={handleStartDeviceFlow}
                >
                  Try again
                </button>
              </div>
            )}

            <button
              type="button"
              className="login-back-button"
              onClick={handleCancel}
            >
              ← Back to sign in options
            </button>
          </div>
        )}

        {/* Client Credentials Form */}
        {mode === 'client-credentials' && (
          <form
            className="login-credentials-form animate-fade-in-up"
            onSubmit={handleCredentialsSubmit}
          >
            <div className="login-field">
              <label htmlFor="client-id" className="login-label">
                Client ID
              </label>
              <input
                id="client-id"
                type="text"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                className="login-input"
                placeholder="Enter your client ID"
                autoComplete="username"
                autoFocus
                required
              />
            </div>

            <div className="login-field">
              <label htmlFor="client-secret" className="login-label">
                Client Secret
              </label>
              <input
                id="client-secret"
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                className="login-input"
                placeholder="Enter your client secret"
                autoComplete="current-password"
                required
              />
            </div>

            {credentialsError && (
              <div className="login-credentials-error" role="alert">
                <span className="login-error-icon">⚠️</span>
                {credentialsError}
              </div>
            )}

            <button
              type="submit"
              className="login-submit-button"
              disabled={isSubmitting || !clientId || !clientSecret}
            >
              {isSubmitting ? (
                <>
                  <span className="login-status-spinner small" aria-hidden="true" />
                  Signing in...
                </>
              ) : (
                'Sign in'
              )}
            </button>

            <button
              type="button"
              className="login-back-button"
              onClick={() => setMode('select')}
            >
              ← Back to sign in options
            </button>
          </form>
        )}

        {/* Footer */}
        <footer className="login-footer">
          <p>
            By signing in, you agree to our{' '}
            <a href="/terms">Terms of Service</a> and{' '}
            <a href="/privacy">Privacy Policy</a>.
          </p>
        </footer>
      </div>
    </div>
  );
}

export default LoginPage;
