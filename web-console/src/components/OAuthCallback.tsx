/**
 * OAuthCallback Component
 *
 * Handles OAuth callback redirects from social login providers (GitHub, Google).
 * Exchanges the authorization code for tokens and completes the login flow.
 *
 * Following:
 * - behavior_prototype_consent_ux (Teacher)
 * - behavior_lock_down_security_surface (Student)
 */

import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import './OAuthCallback.css';

type CallbackStatus = 'processing' | 'success' | 'error';

// Module-level state to handle React StrictMode double-execution
// This survives component remounts within the same page load
let processingPromise: Promise<void> | null = null;
let processingCode: string | null = null;

export function OAuthCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { completeOAuthLogin, isAuthenticated, logout } = useAuth();

  const [status, setStatus] = useState<CallbackStatus>('processing');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    async function handleCallback() {
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const error = searchParams.get('error');
      const errorDescription = searchParams.get('error_description');

      // Check for OAuth error from provider
      if (error) {
        setStatus('error');
        setErrorMessage(errorDescription ?? `OAuth error: ${error}`);
        return;
      }

      // Validate required parameters
      if (!code) {
        if (isAuthenticated) {
          navigate('/', { replace: true });
          return;
        }
        setStatus('error');
        setErrorMessage('Missing authorization code');
        return;
      }

      // If we're already processing THIS code, wait for that result
      if (processingCode === code && processingPromise) {
        // StrictMode double-execution detected—silently wait for the first attempt
        try {
          await processingPromise;
          if (mountedRef.current) {
            setStatus('success');
            setTimeout(() => navigate('/', { replace: true }), 1500);
          }
        } catch (err) {
          if (mountedRef.current) {
            setStatus('error');
            setErrorMessage(err instanceof Error ? err.message : 'Authentication failed');
          }
        }
        return;
      }

      // Start processing this code
      processingCode = code;

      const doExchange = async () => {
        // Clear any stale auth state before attempting OAuth
        try {
          await logout();
        } catch {
          // Ignore logout errors
        }

        // Exchange code for tokens
        await completeOAuthLogin(code, state ?? undefined);
      };

      processingPromise = doExchange();

      try {
        await processingPromise;
        if (mountedRef.current) {
          setStatus('success');
          setTimeout(() => navigate('/', { replace: true }), 1500);
        }
      } catch (err) {
        if (mountedRef.current) {
          setStatus('error');
          setErrorMessage(err instanceof Error ? err.message : 'Failed to complete authentication');
        }
        throw err; // Re-throw so waiting promises also get the error
      } finally {
        processingPromise = null;
        processingCode = null;
      }
    }

    handleCallback();
  }, [searchParams, completeOAuthLogin, navigate, isAuthenticated, logout]);

  return (
    <div className="oauth-callback-page">
      <div className="oauth-callback-container">
        {status === 'processing' && (
          <div className="oauth-callback-processing">
            <div className="oauth-callback-spinner" aria-hidden="true" />
            <h2>Completing sign in...</h2>
            <p>Please wait while we verify your credentials.</p>
          </div>
        )}

        {status === 'success' && (
          <div className="oauth-callback-success">
            <span className="oauth-callback-icon" aria-hidden="true">✓</span>
            <h2>Sign in successful!</h2>
            <p>Redirecting to your dashboard...</p>
          </div>
        )}

        {status === 'error' && (
          <div className="oauth-callback-error">
            <span className="oauth-callback-icon error" aria-hidden="true">✕</span>
            <h2>Sign in failed</h2>
            <p>{errorMessage}</p>
            <button
              type="button"
              className="oauth-callback-retry"
              onClick={() => navigate('/login', { replace: true })}
            >
              Return to sign in
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default OAuthCallback;
