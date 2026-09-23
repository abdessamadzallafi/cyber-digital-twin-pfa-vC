import {
  DRONE_STALE_AFTER_SECONDS,
  getDroneFreshness,
  mergeDroneRest,
  mergeDroneTelemetry,
  nextWebSocketStatus,
  shouldReconnect,
} from './realtime';

describe('PATCH4B realtime contracts', () => {
  test('WebSocket CONNECTING becomes LIVE only after open', () => {
    expect(nextWebSocketStatus('CONNECTING', 'open')).toBe('LIVE');
    expect(nextWebSocketStatus('CONNECTING', 'connecting')).toBe('CONNECTING');
  });

  test('WebSocket close becomes DISCONNECTED and auth close becomes AUTH_ERROR', () => {
    expect(nextWebSocketStatus('LIVE', 'close')).toBe('DISCONNECTED');
    expect(nextWebSocketStatus('LIVE', 'auth_error')).toBe('AUTH_ERROR');
  });

  test('recent drone telemetry replaces older REST state', () => {
    const rest = mergeDroneRest({}, {
      drone_id: 'drone_01', x: 1, y: 2, altitude: 3, battery: 90,
      status: 'idle', updated_at: 100,
    });
    const live = mergeDroneTelemetry(rest, {
      type: 'drone_telemetry', drone_id: 'drone_01', mission_id: 'm1',
      status: 'flying', position: { x: 4, y: 5, altitude: 6 }, battery: 80,
      timestamp: 110,
    });
    expect(live.position).toEqual({ x: 4, y: 5, altitude: 6 });
    expect(live.battery).toBe(80);
    expect(live.lastDroneTelemetryAt).toBe(110);
  });

  test('older REST state cannot replace newer WebSocket telemetry', () => {
    const current = mergeDroneTelemetry({}, {
      type: 'drone_telemetry', drone_id: 'drone_01', status: 'flying',
      position: { x: 4, y: 5, altitude: 6 }, battery: 80, timestamp: 110,
    });
    const result = mergeDroneRest(current, {
      drone_id: 'drone_01', x: 1, y: 2, altitude: 3, battery: 90,
      status: 'idle', updated_at: 100,
    });
    expect(result.position).toEqual(current.position);
    expect(result.battery).toBe(80);
    expect(result.status).toBe('flying');
  });

  test('REST status initializes valid drone fields without claiming telemetry', () => {
    const result = mergeDroneRest({}, {
      drone_id: 'drone_01', x: 1, y: 2, altitude: 3, battery: 90,
      status: 'idle', updated_at: 100,
    });
    expect(result.position).toEqual({ x: 1, y: 2, altitude: 3 });
    expect(result.battery).toBe(90);
    expect(result.telemetry_received).not.toBe(true);
    expect(result.lastDroneTelemetryAt).toBeUndefined();
  });

  test('missing position and battery are never invented', () => {
    const result = mergeDroneTelemetry({}, {
      type: 'drone_telemetry', drone_id: 'drone_01', status: 'idle', timestamp: 110,
    });
    expect(result.position).toBeNull();
    expect(result.battery).toBeNull();
  });

  test('drone freshness distinguishes UNKNOWN, LIVE, STALE and DISCONNECTED', () => {
    expect(getDroneFreshness({ lastTelemetryAt: null, now: 100, wsStatus: 'LIVE' })).toBe('UNKNOWN');
    expect(getDroneFreshness({ lastTelemetryAt: 95, now: 100, wsStatus: 'LIVE' })).toBe('LIVE');
    expect(getDroneFreshness({ lastTelemetryAt: 100 - DRONE_STALE_AFTER_SECONDS - 1, now: 100, wsStatus: 'LIVE' })).toBe('STALE');
    expect(getDroneFreshness({ lastTelemetryAt: 80, now: 100, wsStatus: 'DISCONNECTED' })).toBe('DISCONNECTED');
  });

  test('invalid or missing telemetry timestamp does not update live state', () => {
    const result = mergeDroneTelemetry({}, {
      type: 'drone_telemetry', status: 'idle', position: { x: 1, y: 2, altitude: 3 }, battery: 90,
    });
    expect(result.lastDroneTelemetryAt).toBeUndefined();
    expect(result.position).toBeUndefined();
  });

  test('reconnect policy stops after auth error or attempt limit', () => {
    expect(shouldReconnect({ disposed: false, authError: false, attempts: 0, maxAttempts: 5 })).toBe(true);
    expect(shouldReconnect({ disposed: false, authError: true, attempts: 0, maxAttempts: 5 })).toBe(false);
    expect(shouldReconnect({ disposed: false, authError: false, attempts: 5, maxAttempts: 5 })).toBe(false);
    expect(shouldReconnect({ disposed: true, authError: false, attempts: 0, maxAttempts: 5 })).toBe(false);
  });
});
