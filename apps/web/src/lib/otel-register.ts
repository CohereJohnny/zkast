/**
 * Loaded only when ZKAST_OTEL_ENABLED=true (see instrumentation.ts).
 */
export async function registerOtel(): Promise<void> {
  const { NodeSDK } = await import("@opentelemetry/sdk-node");

  const sdk = new NodeSDK({
    serviceName: "zkast-web",
  });
  sdk.start();
}
