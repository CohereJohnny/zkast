export async function register() {
  if (process.env.ZKAST_OTEL_ENABLED !== "true") {
    return;
  }
  const { registerOtel } = await import("./lib/otel-register");
  await registerOtel();
}
