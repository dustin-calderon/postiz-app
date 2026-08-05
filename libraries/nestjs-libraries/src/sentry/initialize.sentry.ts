import { capitalize } from 'lodash';

/**
 * Sentry's modules are required lazily, inside the function and *after* the DSN
 * guard. That placement is the whole point of this file's shape — do not hoist
 * them back to the top.
 *
 * `@sentry/profiling-node` loads a native binary (`sentry_cpu_profiler.node`)
 * at import time. As a top-level import it did so on every boot, DSN or not,
 * because `main.ts` calls this before anything else. On 2026-08-04 that wedged
 * the backend for 2h38m during a container start: it never reached
 * `NestFactory.create()`, never logged a line, had to be SIGKILLed, and the
 * hung process had that binary as its only loaded native module (a healthy one
 * loads six). It is a race — it does not reproduce on an idle box — so the fix
 * is to remove the load entirely when it can serve no purpose.
 *
 * Ordering is unchanged for the case that matters: `main.ts` still calls this
 * before every other require, so when a DSN *is* configured Sentry still
 * installs its instrumentation ahead of Nest, express and the rest.
 *
 * Note this does not keep the Sentry SDK out of the process altogether:
 * `sentry.exception.ts` imports `@sentry/nestjs/setup` for `SentryGlobalFilter`
 * and that arrives later via `app.module`. What stays out without a DSN is the
 * native profiler, which is the part that hung.
 */
export const initializeSentry = (appName: string, allowLogs = false) => {
  if (!process.env.NEXT_PUBLIC_SENTRY_DSN) {
    return null;
  }

  try {
    const Sentry = require('@sentry/nestjs');
    const { nodeProfilingIntegration } = require('@sentry/profiling-node');

    Sentry.init({
      initialScope: {
        tags: {
          service: appName,
          component: 'nestjs',
        },
        contexts: {
          app: {
            name: `Postiz ${capitalize(appName)}`,
          },
        },
      },
      environment: process.env.NODE_ENV || 'development',
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      spotlight: process.env.SENTRY_SPOTLIGHT === '1',
      integrations: [
        // Add our Profiling integration
        nodeProfilingIntegration(),
        Sentry.consoleLoggingIntegration({ levels: ['log', 'info', 'warn', 'error', 'debug', 'assert', 'trace'] }),
        Sentry.openAIIntegration({
          recordInputs: true,
          recordOutputs: true,
        }),
      ],
      tracesSampleRate: 1.0,
      enableLogs: true,

      // Profiling
      profileSessionSampleRate: process.env.NODE_ENV === 'development' ? 1.0 : 0.45,
      profileLifecycle: 'trace',
    });
  } catch (err) {
    console.log(err);
  }
  return true;
};
