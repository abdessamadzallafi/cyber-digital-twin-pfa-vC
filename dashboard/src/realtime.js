export const DRONE_STALE_AFTER_SECONDS = 10;

const finiteNumber = value => typeof value === 'number' && Number.isFinite(value);

export const validPosition = position => Boolean(
  position && finiteNumber(position.x) && finiteNumber(position.y) && finiteNumber(position.altitude)
);

const withPosition = data => {
  if (validPosition(data.position)) return data.position;
  if (finiteNumber(data.x) && finiteNumber(data.y) && finiteNumber(data.altitude)) {
    return { x: data.x, y: data.y, altitude: data.altitude };
  }
  return null;
};

const patchDroneFields = (previous, data) => {
  const next = {
    position: previous.position ?? null,
    battery: previous.battery ?? null,
    ...previous,
  };
  if (typeof data.drone_id === 'string' && data.drone_id) next.drone_id = data.drone_id;
  if (typeof data.mission_id === 'string' || data.mission_id === null) next.mission_id = data.mission_id;
  if (typeof data.status === 'string' && data.status) next.status = data.status;
  const position = withPosition(data);
  if (position) next.position = position;
  if (finiteNumber(data.battery)) next.battery = data.battery;
  return next;
};

export const mergeDroneRest = (previous, data) => {
  if (!data || typeof data !== 'object') return previous;
  const timestamp = finiteNumber(data.updated_at) ? data.updated_at : null;
  const previousTimestamp = previous.lastDroneTelemetryAt ?? previous.restUpdatedAt ?? null;
  if (timestamp !== null && previousTimestamp !== null && timestamp <= previousTimestamp) return previous;
  const next = patchDroneFields(previous, data);
  return {
    ...next,
    restUpdatedAt: timestamp ?? previous.restUpdatedAt ?? null,
  };
};

export const mergeDroneTelemetry = (previous, data) => {
  if (!data || data.type !== 'drone_telemetry' || !finiteNumber(data.timestamp)) return previous;
  if (finiteNumber(previous.lastDroneTelemetryAt) && data.timestamp <= previous.lastDroneTelemetryAt) return previous;
  const next = patchDroneFields(previous, data);
  return {
    ...next,
    telemetry_received: true,
    lastDroneTelemetryAt: data.timestamp,
    updated_at: data.timestamp,
    source: 'websocket',
  };
};

export const getDroneFreshness = ({ lastTelemetryAt, now, wsStatus }) => {
  if (!finiteNumber(lastTelemetryAt) || !finiteNumber(now)) {
    return wsStatus === 'DISCONNECTED' ? 'DISCONNECTED' : 'UNKNOWN';
  }
  const age = now - lastTelemetryAt;
  if (age <= DRONE_STALE_AFTER_SECONDS) return 'LIVE';
  return wsStatus === 'DISCONNECTED' ? 'DISCONNECTED' : 'STALE';
};

export const nextWebSocketStatus = (current, event) => {
  if (event === 'open') return 'LIVE';
  if (event === 'auth_error') return 'AUTH_ERROR';
  if (event === 'close' || event === 'error') return 'DISCONNECTED';
  return current;
};

export const shouldReconnect = ({ disposed, authError, attempts, maxAttempts }) => (
  !disposed && !authError && attempts < maxAttempts
);
