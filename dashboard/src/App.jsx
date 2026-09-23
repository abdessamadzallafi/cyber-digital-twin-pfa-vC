import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import './App.css';
import {
  getDroneFreshness,
  mergeDroneRest,
  mergeDroneTelemetry,
  nextWebSocketStatus,
  shouldReconnect,
} from './realtime';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WS_URL = process.env.REACT_APP_WS_URL || API.replace(/^http/, 'ws') + '/ws';

const DEVICE_LABELS = {
  grue_G01: 'Grue G01', station_H01: 'Station humidité', portique_P01: 'Portique P01',
  camera_Q01: 'Caméra quai', camion_C12: 'Camion C12', portail_N01: 'Portail nord',
  entrepot_E01: 'Entrepôt E01', parking_P01: 'Parking'
};

const DEVICE_TYPES = {
  grue_G01: 'GR', station_H01: 'HU', portique_P01: 'PO', camera_Q01: 'CA',
  camion_C12: 'TR', portail_N01: 'AC', entrepot_E01: 'SE', parking_P01: 'PK'
};

const MAP_POSITIONS = {
  grue_G01:     [38, 68],
  portique_P01: [52, 58],
  camera_Q01:   [45, 48],
  entrepot_E01: [68, 55],
  station_H01:  [58, 70],
  portail_N01:  [76, 62],
  camion_C12:   [82, 72],
  parking_P01:  [74, 78]
};

const NAVIGATION = [
  ['overview', 'Vue d’ensemble', '⌂'], ['devices', 'Équipements', '◈'], ['security', 'Sécurité', '◉'],
  ['missions', 'Missions', '◎'], ['incidents', 'Incidents', '⚠'], ['timeline', 'Activité', '≡'], ['datalake', 'Data Lake', '◫'], ['reports', 'Rapports', '▤']
];

const asArray = value => Array.isArray(value) ? value : [];
const statusOf = value => value == null ? 'unavailable' : value === 'red' ? 'critical' : value === 'yellow' ? 'warning' : 'healthy';
const labelStatus = value => value == null ? 'Indisponible' : value === 'red' ? 'Critique' : value === 'yellow' ? 'À surveiller' : 'Opérationnel';
const number = value => Number(value).toLocaleString('fr-FR');
const displayValue = (value, formatter = value => value) => value == null ? 'N/A' : formatter(value);
const hasPosition = position => position && [position.x, position.y, position.altitude].every(value => typeof value === 'number');

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [tab, setTab] = useState('overview');
  const [devices, setDevices] = useState({});
  const [deviceList, setDeviceList] = useState(null);
  const [deviceState, setDeviceState] = useState('loading');
  const [stats, setStats] = useState(null);
  const [statsState, setStatsState] = useState('loading');
  const [health, setHealth] = useState({});
  const [risk, setRisk] = useState(null);
  const [events, setEvents] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [missions, setMissions] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [lake, setLake] = useState({ streams: {} });
  const [drone, setDrone] = useState({ telemetry_received: false, position: null, battery: null, status: null, mission_id: null, lastDroneTelemetryAt: null, restUpdatedAt: null });
  const [droneState, setDroneState] = useState('loading');
  const [wsStatus, setWsStatus] = useState('DISCONNECTED');
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [history, setHistory] = useState([]);
  const [now, setNow] = useState(new Date());
  const ws = useRef(null);
  const authError = useRef(false);

  const authFetch = useCallback((path, options = {}) => fetch(`${API}${path}`, {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  }), [token]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const get = async path => {
      try {
        const response = await authFetch(path);
        if (response.status === 401) {
          authError.current = true;
          setWsStatus('AUTH_ERROR');
          ws.current?.close(1008, 'authentication required');
        }
        if (!response.ok) return { ok: false, data: null };
        return { ok: true, data: await response.json() };
      } catch {
        return { ok: false, data: null };
      }
    };
    const [nextStats, nextRisk, nextDevices, nextIncidents, nextMissions, nextTimeline, nextDrone, nextLake] = await Promise.all([
      get('/statistics'), get('/risk'), get('/devices'), get('/incidents'), get('/missions'), get('/timeline'), get('/drone/status'), get('/api/v1/datalake')
    ]);
    if (nextStats.ok && nextStats.data) {
      setStats(nextStats.data);
      setStatsState('ready');
    } else {
      setStats(null);
      setStatsState('error');
    }
    setRisk(nextRisk.ok ? nextRisk.data : null);
    if (nextDevices.ok && Array.isArray(nextDevices.data)) {
      setDeviceList(nextDevices.data);
      setDeviceState('ready');
      const healthResults = await Promise.all(nextDevices.data.map(async device => {
        const result = await get(`/health/${device.device_id}`);
        return [device.device_id, result.ok ? result.data?.health_score : null];
      }));
      setHealth(Object.fromEntries(healthResults));
    } else {
      setDeviceList(null);
      setDeviceState('error');
      setHealth({});
    }
    if (nextIncidents.ok && Array.isArray(nextIncidents.data)) setIncidents(nextIncidents.data);
    if (nextMissions.ok && Array.isArray(nextMissions.data)) setMissions(nextMissions.data);
    if (nextTimeline.ok && Array.isArray(nextTimeline.data)) setTimeline(nextTimeline.data);
    if (nextDrone.ok && nextDrone.data) {
      setDrone(previous => mergeDroneRest(previous, nextDrone.data));
      setDroneState('ready');
    } else {
      setDroneState('error');
    }
    if (nextLake.ok && nextLake.data) setLake(nextLake.data);
  }, [authFetch, token]);

  useEffect(() => {
    if (!token) return;
    refresh();
    const interval = window.setInterval(refresh, 5000);
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    return () => { window.clearInterval(interval); window.clearInterval(clock); };
  }, [refresh, token]);

  useEffect(() => {
    if (!token) {
      setWsStatus('AUTH_ERROR');
      return undefined;
    }
    authError.current = false;
    const separator = WS_URL.includes('?') ? '&' : '?';
    let disposed = false;
    let socket = null;
    let reconnectTimer = null;
    let attempts = 0;
    const maxAttempts = 5;

    const scheduleReconnect = () => {
      if (!shouldReconnect({ disposed, authError: authError.current, attempts, maxAttempts })) return;
      const delay = Math.min(1000 * (2 ** attempts), 10000);
      attempts += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    };

    const connect = () => {
      if (disposed || authError.current || !token) return;
      if (socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(socket.readyState)) return;
      setWsStatus('CONNECTING');
      socket = new WebSocket(`${WS_URL}${separator}token=${encodeURIComponent(token)}`);
      ws.current = socket;
      socket.onopen = () => {
        attempts = 0;
        setWsStatus(nextWebSocketStatus('CONNECTING', 'open'));
      };
      socket.onmessage = ({ data }) => {
        try {
          const update = JSON.parse(data);
          if (update.type === 'drone_telemetry') {
            setDrone(previous => mergeDroneTelemetry(previous, update));
          }
          if (update.device_id) {
            setDevices(previous => ({ ...previous, [update.device_id]: { ...previous[update.device_id], ...update } }));
            setEvents(previous => [{ ...update, time: new Date().toLocaleTimeString('fr-FR') }, ...previous].slice(0, 30));
          }
        } catch {
          // Ignore malformed broadcast payloads without breaking the socket lifecycle.
        }
      };
      socket.onerror = () => {
        if (!disposed) setWsStatus(nextWebSocketStatus('LIVE', 'error'));
      };
      socket.onclose = event => {
        if (disposed) return;
        if (ws.current === socket) ws.current = null;
        if (event.code === 1008) {
          authError.current = true;
          setWsStatus(nextWebSocketStatus('LIVE', 'auth_error'));
          return;
        }
        setWsStatus(nextWebSocketStatus('LIVE', 'close'));
        scheduleReconnect();
      };
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        socket.close();
      }
      if (ws.current === socket) ws.current = null;
    };
  }, [token]);

  const login = async event => {
    event?.preventDefault();
    setLoggingIn(true); setLoginError('');
    try {
      const response = await fetch(`${API}/token`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ username, password }) });
      if (!response.ok) throw new Error('Identifiants incorrects.');
      const data = await response.json();
      localStorage.setItem('token', data.access_token); setToken(data.access_token);
    } catch (error) { setLoginError(error.message || 'Le serveur est indisponible.'); }
    setLoggingIn(false);
  };

  const logout = () => { localStorage.removeItem('token'); setToken(''); };
  const launch = path => authFetch(path, { method: 'POST' }).then(refresh).catch(console.error);
  const openHistory = id => authFetch(`/measures/${id}?limit=24`).then(r => r.json()).then(data => {
    setHistory(asArray(data).map(row => ({ time: new Date(row.timestamp * 1000).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }), value: row.value ?? row.people_count ?? 0 })).reverse());
    setSelectedDevice(id);
  }).catch(console.error);
  const report = id => authFetch(`/report/${id}?anomaly_type=ml_anomaly`, { method: 'POST' }).then(r => r.json()).then(data => window.alert(`Rapport créé : ${data.filename}`));

  if (!token) return (
    <main className="login-page">
      <section className="login-panel">
        <div className="brand-mark">◈</div>
        <p className="eyebrow">SecurIoT-Port / TANGER MED</p>
        <h1>Le port, sous contrôle.</h1>
        <p className="login-copy">Supervisez les équipements, les opérations et la sécurité de votre terminal en temps réel.</p>
        <form onSubmit={login}>
          <label>Identifiant<input autoFocus value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" /></label>
          <label>Mot de passe<input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" /></label>
          {loginError && <p className="form-error">{loginError}</p>}
          <button className="primary-button" disabled={loggingIn}>{loggingIn ? 'Connexion…' : 'Accéder au poste de contrôle'} <span>→</span></button>
        </form>
        <p className="login-footer"><i /> Connexion sécurisée · Terminal Tanger Med</p>
      </section>
      <aside className="login-art" style={{backgroundImage:"url('/port.jpeg')",backgroundSize:"cover",backgroundPosition:"center 40%",position:"relative"}}>
        <div style={{position:"absolute",inset:0,background:"linear-gradient(to right, rgba(10,22,40,0.85) 0%, rgba(10,22,40,0.55) 100%)",zIndex:1}} />
        <div className="art-copy" style={{position:"relative",zIndex:2}}>
          <span className="live-pill"><i /> AUTHENTIFICATION REQUISE</span>
          <strong>Une vision unifiée<br />de chaque opération.</strong>
          <p>IoT, intelligence artificielle et sécurité réunis dans une seule interface.</p>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginTop:"1.5rem"}}>
            <div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}>
              <div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>N/A</div>
              <div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>ÉQUIPEMENTS IoT</div>
            </div>
            <div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}>
              <div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>24/7</div>
              <div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>SURVEILLANCE</div>
            </div>
            <div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}>
              <div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>AI</div>
              <div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>DÉTECTION AVANCÉE</div>
            </div>
            <div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}>
              <div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>DRONE</div>
              <div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>INSPECTION</div>
            </div>
          </div>
        </div>
      </aside>
    </main>
  );

  const activeEvents = events.length ? events : asArray(timeline).slice(0, 5).map(event => ({ ...event, device_id: event.type, last_value: event.message, time: new Date(event.time).toLocaleTimeString('fr-FR') }));
  const dangerCount = asArray(incidents).filter(item => item.status !== 'resolved').length;
  const droneFreshness = getDroneFreshness({ lastTelemetryAt: drone.lastDroneTelemetryAt, now: now.getTime() / 1000, wsStatus });

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="side-brand"><span>◈</span><div>PORT<span>OS</span><small>Surveillance IoT</small></div></div>
        <nav>
          {NAVIGATION.map(([id, name, icon]) => (
            <button key={id} className={tab === id ? 'selected' : ''} onClick={() => setTab(id)}>
              <b>{icon}</b>{name}{id === 'incidents' && dangerCount > 0 && <em>{dangerCount}</em>}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <div className="operator"><span>AM</span><p>Administrateur<small>Accès sécurisé</small></p></div>
          <button className="logout" onClick={logout}>⇥ Déconnexion</button>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="breadcrumb">POSTE DE CONTRÔLE / {NAVIGATION.find(item => item[0] === tab)?.[1].toUpperCase()}</p>
            <h1>{tab === 'overview' ? 'Bonjour, Administrateur.' : NAVIGATION.find(item => item[0] === tab)?.[1]}</h1>
          </div>
          <div className="topbar-actions">
            <span className={`live-pill ${wsStatus.toLowerCase()}`}><i /> {wsStatus === 'AUTH_ERROR' ? 'Session expirée' : `WS ${wsStatus}`}</span>
            <span className="date">{now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}<b>{now.toLocaleTimeString('fr-FR')}</b></span>
            <button className="icon-button" aria-label="Notifications">♧<em>{stats?.total_alerts ?? ''}</em></button>
          </div>
        </header>
        {tab === 'overview' && <Overview stats={stats} statsState={statsState} risk={risk} deviceList={deviceList} deviceState={deviceState} devices={devices} health={health} drone={drone} droneState={droneState} droneFreshness={droneFreshness} events={activeEvents} incidents={incidents} onDevice={openHistory} onAttack={launch} onMission={() => launch('/force_mission/entrepot_E01')} />}
        {tab === 'devices' && <Devices deviceList={deviceList} deviceState={deviceState} devices={devices} health={health} onDevice={openHistory} />}
        {tab === 'security' && <Security stats={stats} risk={risk} events={activeEvents} onAttack={launch} />}
        {tab === 'missions' && <Missions missions={missions} drone={drone} droneFreshness={droneFreshness} onMission={() => launch('/force_mission/entrepot_E01')} />}
        {tab === 'incidents' && <Incidents incidents={incidents} />}
        {tab === 'timeline' && <Timeline timeline={timeline} />}
        {tab === 'datalake' && <DataLake lake={lake} />}
        {tab === 'reports' && <Reports onReport={() => selectedDevice ? report(selectedDevice) : openHistory('entrepot_E01')} />}
      </main>
      {selectedDevice && <History device={selectedDevice} history={history} close={() => setSelectedDevice(null)} report={report} />}
    </div>
  );
}

function Overview({ stats, statsState, risk, deviceList, deviceState, devices, health, drone, droneState, droneFreshness, events, incidents, onDevice, onAttack, onMission }) {
  const robot = drone;
  const cards = [
    ['Équipements connectés', stats ? displayValue(stats.active_devices, number) : statsState === 'loading' ? 'Chargement…' : 'Indisponible', stats ? `${displayValue(stats.total_devices, number)} enregistrés` : 'Donnée indisponible', 'teal'],
    ['Alertes actives', stats ? displayValue(stats.total_alerts, number) : statsState === 'loading' ? 'Chargement…' : 'Indisponible', 'À traiter', 'amber'],
    ['Événements de sécurité', stats ? displayValue(stats.attacks, number) : statsState === 'loading' ? 'Chargement…' : 'Indisponible', 'Sécurité réseau', 'red'],
    ['Niveau de risque', risk ? displayValue(risk.risk_score, value => `${Number(value).toFixed(0)}%`) : 'N/A', risk?.level || 'Niveau indisponible', 'purple']
  ];
  return (
    <>
      <section className="stat-grid">
        {cards.map(([title, value, foot, tone]) => (
          <article className={`metric ${tone}`} key={title}>
            <span>{title}</span>
            <strong>{typeof value === "number" ? number(value) : value}</strong>
            <small><i /> {foot}</small>
          </article>
        ))}
      </section>
      <section className="overview-grid">
        <article className="panel map-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">VUE OPÉRATIONNELLE</p><h2>Terminal Tanger Med</h2></div>
            <button className="text-button">Vue satellite ↗</button>
          </div>
          <div className="terminal-map" style={{position:'relative',overflow:'hidden',backgroundImage:"url('/port.jpeg')",backgroundSize:'cover',backgroundPosition:'center 40%',height:380,borderRadius:9}}>
            <div style={{position:'absolute',inset:0,background:'linear-gradient(160deg,rgba(10,30,40,0.5) 0%,rgba(10,40,55,0.25) 100%)',zIndex:1}}/>
            <div style={{position:'absolute',top:14,left:16,zIndex:3,background:'rgba(255,255,255,0.15)',backdropFilter:'blur(8px)',borderRadius:8,padding:'6px 12px',border:'1px solid rgba(255,255,255,0.25)'}}>
              <span style={{fontSize:8,fontFamily:'DM Mono',letterSpacing:2,color:'#a0f0e8',textTransform:'uppercase'}}>📡 Vue Satellite · Tanger Med</span>
            </div>
            {deviceState === 'loading' && <p className="empty">Chargement des équipements…</p>}
            {deviceState === 'error' && <p className="empty">Équipements indisponibles.</p>}
            {deviceState === 'ready' && deviceList.length === 0 && <p className="empty">Aucun équipement disponible.</p>}
            {deviceState === 'ready' && deviceList.filter(device => MAP_POSITIONS[device.device_id]).map(device => {
              const id = device.device_id;
              const [left, top] = MAP_POSITIONS[id];
              const data = devices[id] || {};
              return (
                <button key={id} className={`map-node ${statusOf(data.status)}`} style={{left:`${left}%`,top:`${top}%`,zIndex:2}} onClick={() => onDevice(id)}>
                  <b>{DEVICE_TYPES[id]}</b>
                  <span>{DEVICE_LABELS[id]}</span>
                  <i />
                </button>
              );
            })}
            {robot.telemetry_received && hasPosition(robot.position) && <div className={`robot-pin ${robot.status && robot.status !== 'idle' ? 'moving' : ''}`} style={{left:`${robot.position.x}%`,top:`${robot.position.y}%`,zIndex:3}}>✦<span>DRONE-01</span></div>}
            <div className="map-key" style={{zIndex:3}}>
              <span><i className="dot healthy"/> Opérationnel</span>
              <span><i className="dot warning"/> Attention</span>
              <span><i className="dot critical"/> Alerte</span>
            </div>
          </div>
        </article>
        <article className="panel event-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">FLUX EN DIRECT</p><h2>Derniers événements</h2></div>
            <span className="count-chip">{events.length}</span>
          </div>
          <div className="event-list">
            {events.length ? events.map((event, index) => (
              <div className="event" key={index}>
                <span className={`event-icon ${statusOf(event.status)}`}>{event.status === 'red' ? '!' : '◌'}</span>
                <p><b>{DEVICE_LABELS[event.device_id] || event.device_id || 'Événement système'}</b><span>{event.last_value ?? event.value ?? 'Nouvelle activité détectée'}</span></p>
                <time>{event.time}</time>
              </div>
            )) : <p className="empty">En attente d’activité…</p>}
          </div>
          <button className="panel-link">Voir tout le journal →</button>
        </article>
      </section>
      <section className="bottom-grid">
        <article className="panel fleet-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">INSPECTION AUTONOME</p><h2>Drone d’inspection</h2></div>
            <span className={`status-chip ${droneFreshness === 'LIVE' ? 'healthy' : droneFreshness === 'STALE' ? 'warning' : 'unavailable'}`}>{droneFreshness === 'LIVE' ? 'LIVE' : droneFreshness === 'STALE' ? 'STALE' : droneFreshness === 'DISCONNECTED' ? 'DISCONNECTED' : droneState === 'loading' ? 'Chargement…' : 'UNKNOWN'}</span>
          </div>
          <div className="robot-content">
            <div className="robot-avatar">✦</div>
            <div>
              <b>DRONE-01</b>
              <p>{robot.mission_id ? `Mission ${robot.mission_id}` : 'Aucune mission assignée'}</p>
              <div className="battery"><span style={{ width: `${typeof robot.battery === 'number' ? robot.battery : 0}%` }} /></div>
              <small>Batterie {robot.telemetry_received ? displayValue(robot.battery, value => `${value}%`) : 'N/A'} · {robot.telemetry_received && hasPosition(robot.position) ? `Position ${robot.position.x}, ${robot.position.y}` : 'Position indisponible'}</small>
            </div>
            <button className="secondary-button" onClick={onMission}>Déployer</button>
          </div>
        </article>
        <article className="panel action-panel">
          <div><p className="eyebrow">SIMULATION</p><h2>Tester la résilience</h2><p>Déclenchez des scénarios contrôlés pour valider la détection.</p></div>
          <div className="quick-actions">
            <button onClick={() => onAttack('/simulate/flood')}>≈<span>Flood MQTT</span></button>
            <button onClick={() => onAttack('/simulate/spoof')}>◒<span>Spoofing</span></button>
            <button onClick={() => onAttack('/simulate/impossible')}>⚠<span>Valeur impossible</span></button>
          </div>
        </article>
      </section>
    </>
  );
}

function Devices({ deviceList, deviceState, devices, health, onDevice }) {
  const list = deviceList || [];
  return (
    <section className="panel table-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">INVENTAIRE IOT</p><h2>Équipements du terminal</h2></div>
        <span className="count-chip">{deviceState === 'ready' ? `${list.length} disponibles` : deviceState === 'loading' ? 'Chargement…' : 'Indisponible'}</span>
      </div>
      <div className="device-table">
        <div className="table-head"><span>Équipement</span><span>Zone</span><span>Dernière mesure</span><span>Santé</span><span>État</span></div>
        {deviceState === 'loading' && <p className="empty">Chargement des équipements…</p>}
        {deviceState === 'error' && <p className="empty">Inventaire indisponible.</p>}
        {deviceState === 'ready' && list.length === 0 && <p className="empty">Aucun équipement disponible.</p>}
        {list.map(device => {
          const live = devices[device.device_id] || {};
          const condition = live.status ?? device.status;
          const healthScore = health[device.device_id] ?? device.health_score;
          return (
            <button className="table-row" key={device.device_id} onClick={() => onDevice(device.device_id)}>
              <span className="equipment"><b>{DEVICE_TYPES[device.device_id] || 'IO'}</b>{DEVICE_LABELS[device.device_id] || device.device_id}</span>
              <span>{device.zone || 'N/A'}</span>
              <span>{live.last_value ?? device.last_value ?? '—'}</span>
              <span>{typeof healthScore === 'number' ? <i className="health-bar"><b style={{ width: `${healthScore}%` }} /></i> : null}{displayValue(healthScore, value => `${value}%`)}</span>
              <span className={`status-chip ${statusOf(condition)}`}>{labelStatus(condition)}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Security({ stats, risk, events, onAttack }) {
  const attackCount = stats ? displayValue(stats.attacks, number) : 'Indisponible';
  const alertCount = stats ? displayValue(stats.total_alerts, number) : 'Indisponible';
  const riskValue = risk ? displayValue(risk.risk_score, value => `${Number(value).toFixed(0)}%`) : 'N/A';
  return (
    <>
      <section className="stat-grid security-metrics">
        <article className="metric red"><span>Incidents détectés</span><strong>{attackCount}</strong><small>Source : backend</small></article>
        <article className="metric amber"><span>Alertes ouvertes</span><strong>{alertCount}</strong><small>Source : backend</small></article>
        <article className="metric purple"><span>Indice de risque</span><strong>{riskValue}</strong><small>Niveau {risk?.level || 'indisponible'}</small></article>
      </section>
      <section className="two-column">
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">DÉTECTION</p><h2>Journal de sécurité</h2></div></div>
          <div className="event-list">
            {events.map((event, index) => (
              <div className="event" key={index}>
                <span className={`event-icon ${statusOf(event.status)}`}>!</span>
                <p><b>{event.device_id || 'Système'}</b><span>{event.last_value ?? event.value ?? 'Événement observé'}</span></p>
                <time>{event.time}</time>
              </div>
            ))}
          </div>
        </article>
        <article className="panel scenario-panel">
          <p className="eyebrow">LABORATOIRE</p>
          <h2>Scénarios de sécurité</h2>
          <p>Ces actions simulent des attaques sur l’environnement de démonstration.</p>
          <button className="danger-button" onClick={() => onAttack('/simulate/flood')}>Lancer un flood MQTT <span>→</span></button>
          <button className="outline-button" onClick={() => onAttack('/simulate/spoof')}>Simuler une usurpation</button>
          <button className="outline-button" onClick={() => onAttack('/simulate/impossible')}>Injecter une valeur anormale</button>
        </article>
      </section>
    </>
  );
}

function Missions({ missions, drone, droneFreshness, onMission }) {
  return (
    <section className="two-column">
      <article className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">DRONE-01</p><h2>État de la flotte</h2></div>
          <span className={`status-chip ${droneFreshness === 'LIVE' ? 'healthy' : droneFreshness === 'STALE' ? 'warning' : 'unavailable'}`}>{droneFreshness}</span>
        </div>
        <div className="mission-hero">
          <div className="robot-avatar large">✦</div>
          <div>
            <strong>{drone.status == null ? 'État indisponible' : drone.status === 'idle' ? 'Prêt à intervenir' : 'Intervention en cours'}</strong>
            <p>{drone.mission_id ? `Mission ${drone.mission_id}` : 'Le drone attend sa prochaine mission.'}</p>
            <div className="battery"><span style={{ width: `${typeof drone.battery === 'number' ? drone.battery : 0}%` }} /></div>
            <small>Batterie : {drone.telemetry_received ? displayValue(drone.battery, value => `${value}%`) : 'N/A'} · Position : {drone.telemetry_received && hasPosition(drone.position) ? `${drone.position.x}, ${drone.position.y}` : 'indisponible'}</small>
          </div>
        </div>
        <button className="primary-button compact" onClick={onMission}>Créer une mission d’inspection <span>→</span></button>
      </article>
      <article className="panel">
        <p className="eyebrow">HISTORIQUE</p>
        <h2>Missions récentes</h2>
        <div className="event-list">
          {missions.length ? missions.map((mission, index) => (
            <div className="event" key={index}>
              <span className="event-icon healthy">◎</span>
              <p><b>{mission.mission_id || 'Mission autonome'}</b><span>{mission.device_id || 'Terminal'} · {mission.status || 'pending'}</span></p>
              <time>{mission.created_at ? new Date(mission.created_at).toLocaleTimeString('fr-FR') : '—'}</time>
            </div>
          )) : <p className="empty">Aucune mission enregistrée.</p>}
        </div>
      </article>
    </section>
  );
}

function Incidents({ incidents }) {
  return (
    <section className="panel table-panel">
      <div className="panel-heading"><div><p className="eyebrow">GESTION DES ALERTES</p><h2>Incidents déclarés</h2></div></div>
      <div className="device-table">
        <div className="table-head"><span>Référence</span><span>Équipement</span><span>Type</span><span>Gravité</span><span>État</span></div>
        {incidents.length ? incidents.map(item => (
          <div className="table-row" key={item.id}>
            <span>#INC-{item.id}</span>
            <span>{DEVICE_LABELS[item.device_id] || item.device_id}</span>
            <span>{item.anomaly_type || 'Anomalie'}</span>
            <span className={`severity ${item.severity || 'medium'}`}>{item.severity || 'medium'}</span>
            <span className="status-chip warning">{item.status || 'open'}</span>
          </div>
        )) : <p className="empty">Aucun incident déclaré.</p>}
      </div>
    </section>
  );
}

function Timeline({ timeline }) {
  return (
    <section className="panel timeline-panel">
      <p className="eyebrow">CHRONOLOGIE</p>
      <h2>Activité du terminal</h2>
      <div className="timeline-list">
        {timeline.length ? timeline.map((item, index) => (
          <div className="timeline-row" key={index}>
            <time>{item.time ? new Date(item.time).toLocaleString('fr-FR') : 'À l’instant'}</time>
            <i className={item.type || 'alert'} />
            <div><span>{item.type || 'événement'}</span><p>{item.message}</p></div>
          </div>
        )) : <p className="empty">Aucune activité récente.</p>}
      </div>
    </section>
  );
}

function DataLake({ lake }) {
  const streams = Object.entries(lake.streams || {});
  return (
    <section className="panel table-panel">
      <div className="panel-heading"><div><p className="eyebrow">DATA LAKE · JSONL</p><h2>Preuves opérationnelles append-only</h2></div><span className="status-chip healthy">{lake.retention || 'append-only'}</span></div>
      <div className="device-table">
        <div className="table-head"><span>Flux</span><span>Format</span><span>Fichiers</span><span>Événements</span><span>Usage</span></div>
        {streams.map(([name, data]) => (
          <div className="table-row" key={name}>
            <span>{name}</span>
            <span>{lake.format || 'jsonl'}</span>
            <span>{data.files}</span>
            <span>{number(data.events)}</span>
            <span>Analyse / SIEM</span>
          </div>
        ))}
        {!streams.length && <p className="empty">En attente des données du Data Lake.</p>}
      </div>
    </section>
  );
}

function Reports({ onReport }) {
  return (
    <section className="panel reports-panel">
      <div className="report-icon">▤</div>
      <p className="eyebrow">CENTRE DOCUMENTAIRE</p>
      <h2>Rapports d’incident</h2>
      <p>Générez un rapport PDF depuis l’historique d’un équipement. Les documents sont stockés dans le dossier <code>reports/</code> du projet.</p>
      <button className="primary-button compact" onClick={onReport}>Préparer un rapport <span>→</span></button>
    </section>
  );
}

function History({ device, history, close, report }) {
  return (
    <div className="modal-backdrop" onMouseDown={close}>
      <section className="history-modal" onMouseDown={event => event.stopPropagation()}>
        <button className="close-button" onClick={close}>×</button>
        <p className="eyebrow">TÉLÉMÉTRIE · {DEVICE_TYPES[device] || 'IO'}</p>
        <h2>{DEVICE_LABELS[device] || device}</h2>
        <p className="chart-subtitle">Dernières mesures reçues</p>
        <div className="chart">
          {history.length ? (
            <ResponsiveContainer>
              <LineChart data={history}>
                <CartesianGrid stroke="#e4edf1" vertical={false}/>
                <XAxis dataKey="time" tickLine={false} axisLine={false}/>
                <YAxis tickLine={false} axisLine={false}/>
                <Tooltip/>
                <Line type="monotone" dataKey="value" stroke="#0c9d91" strokeWidth={3} dot={false}/>
              </LineChart>
            </ResponsiveContainer>
          ) : <p className="empty">Aucune mesure disponible.</p>}
        </div>
        <footer>
          <button className="outline-button" onClick={close}>Fermer</button>
          <button className="primary-button compact" onClick={() => report(device)}>Générer le PDF <span>→</span></button>
        </footer>
      </section>
    </div>
  );
}

export default App;
