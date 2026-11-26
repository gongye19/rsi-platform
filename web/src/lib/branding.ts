/** Product identity is separate from the underlying optimization algorithms. */
export const PLATFORM_NAME = 'RSI Platform';
/** Opt-in, build-time switch. Public demo never contacts the experiment service. */
export const DEMO_MODE = process.env.NEXT_PUBLIC_RSI_DEMO === '1';
