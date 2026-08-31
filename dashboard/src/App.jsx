import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import './App.css';

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
const statusOf = value => value === 'red' ? 'critical' : value === 'yellow' ? 'warning' : 'healthy';
const labelStatus = value => value === 'red' ? 'Critique' : value === 'yellow' ? 'À surveiller' : 'Opérationnel';
const number = value => Number(value || 0).toLocaleString('fr-FR');

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [tab, setTab] = useState('overview');
  const [devices, setDevices] = useState({});
  const [deviceList, setDeviceList] = useState([]);
  const [stats, setStats] = useState({ total_devices: 0, active_devices: 0, offline_devices: 0, total_alerts: 0, attacks: 0, ml_anomalies: 0, flood_count: 0, spoof_count: 0, unknown_count: 0 });
  const [health, setHealth] = useState({});
  const [risk, setRisk] = useState({ risk_score: 0, level: 'Low' });
  const [events, setEvents] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [missions, setMissions] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [lake, setLake] = useState({ streams: {} });
  const [drone, setDrone] = useState({ x: 10, y: 10, status: 'idle', battery: 100, mission_id: null, speed: 0 });
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [history, setHistory] = useState([]);
  const [now, setNow] = useState(new Date());
  const ws = useRef(null);

  const authFetch = useCallback((path, options = {}) => fetch(`${API}${path}`, {
    ...options, headers: { ...options.headers, Authorization: `Bearer ${token}` }
  }), [token]);

  const refresh = useCallback(async () => {
    if (!token) return;
    const get = path => authFetch(path).then(r => r.ok ? r.json() : null).catch(() => null);
    const [nextStats, nextRisk, nextDevices, nextIncidents, nextMissions, nextTimeline, nextDrone, nextLake] = await Promise.all([
      get('/statistics'), get('/risk'), get('/devices'), get('/incidents'), get('/missions'), get('/timeline'), get('/drone/status'), get('/api/v1/datalake')
    ]);
    if (nextStats) setStats(nextStats);
    if (nextRisk) setRisk(nextRisk);
    if (Array.isArray(nextDevices)) setDeviceList(nextDevices);
    if (Array.isArray(nextIncidents)) setIncidents(nextIncidents);
    if (Array.isArray(nextMissions)) setMissions(nextMissions);
    if (Array.isArray(nextTimeline)) setTimeline(nextTimeline);
    if (nextDrone) setDrone(previous => ({ ...previous, ...nextDrone }));
    if (nextLake) setLake(nextLake);
    Object.keys(DEVICE_LABELS).forEach(id => get(`/health/${id}`).then(data => data && setHealth(previous => ({ ...previous, [id]: data.health_score }))));
  }, [authFetch, token]);

  useEffect(() => {
    if (!token) return;
    refresh();
    const interval = window.setInterval(refresh, 5000);
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    return () => { window.clearInterval(interval); window.clearInterval(clock); };
  }, [refresh, token]);

  useEffect(() => {
    if (!token) return;
    ws.current = new WebSocket(WS_URL);
    ws.current.onmessage = ({ data }) => {
      const update = JSON.parse(data);
      if (update.type === 'drone') setDrone(previous => ({ ...previous, ...update }));
      if (update.device_id) {
        setDevices(previous => ({ ...previous, [update.device_id]: { ...previous[update.device_id], ...update } }));
        setEvents(previous => [{ ...update, time: new Date().toLocaleTimeString('fr-FR') }, ...previous].slice(0, 30));
      }
    };
    return () => ws.current?.close();
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

  if (!token) return <main className="login-page"><section className="login-panel"><div className="brand-mark">◈</div><p className="eyebrow">CYBERPORT / TANGER MED</p><h1>Le port, sous contrôle.</h1><p className="login-copy">Supervisez les équipements, les opérations et la sécurité de votre terminal en temps réel.</p><form onSubmit={login}><label>Identifiant<input autoFocus value={username} onChange={e => setUsername(e.target.value)} placeholder="admin" /></label><label>Mot de passe<input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" /></label>{loginError && <p className="form-error">{loginError}</p>}<button className="primary-button" disabled={loggingIn}>{loggingIn ? 'Connexion…' : 'Accéder au poste de contrôle'} <span>→</span></button></form><p className="login-footer"><i /> Connexion sécurisée · Terminal Tanger Med</p></section><aside className="login-art" style={{backgroundImage:"url('/port.jpeg')",backgroundSize:"cover",backgroundPosition:"center 40%",position:"relative"}}><div style={{position:"absolute",inset:0,background:"linear-gradient(to right, rgba(10,22,40,0.85) 0%, rgba(10,22,40,0.55) 100%)",zIndex:1}} /><div className="art-copy" style={{position:"relative",zIndex:2}}><span className="live-pill"><i /> SYSTÈME EN LIGNE</span><strong>Une vision unifiée<br />de chaque opération.</strong><p>IoT, intelligence artificielle et sécurité réunis dans une seule interface.</p><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginTop:"1.5rem"}}><div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}><div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>8</div><div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>ÉQUIPEMENTS IoT</div></div><div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}><div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>24/7</div><div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>SURVEILLANCE</div></div><div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}><div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>ML</div><div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>DÉTECTION IA</div></div><div style={{background:"rgba(0,212,180,0.12)",border:"1px solid rgba(0,212,180,0.25)",borderRadius:8,padding:"10px 12px"}}><div style={{fontSize:20,fontWeight:600,color:"#00d4b4",fontFamily:"monospace"}}>SIEM</div><div style={{fontSize:10,color:"#7a9ab0",letterSpacing:1}}>CORRÉLATION</div></div></div></div></aside></main>;

  const activeEvents = events.length ? events : asArray(timeline).slice(0, 5).map(event => ({ ...event, device_id: event.type, last_value: event.message, time: new Date(event.time).toLocaleTimeString('fr-FR') }));
  const dangerCount = asArray(incidents).filter(item => item.status !== 'resolved').length;

  return <div className="shell">
    <aside className="sidebar"><div className="side-brand"><span>◈</span><div>PORT<span>OS</span><small>Surveillance IoT</small></div></div><nav>{NAVIGATION.map(([id, name, icon]) => <button key={id} className={tab === id ? 'selected' : ''} onClick={() => setTab(id)}><b>{icon}</b>{name}{id === 'incidents' && dangerCount > 0 && <em>{dangerCount}</em>}</button>)}</nav><div className="side-bottom"><div className="operator"><span>AM</span><p>Administrateur<small>Accès sécurisé</small></p></div><button className="logout" onClick={logout}>⇥ Déconnexion</button></div></aside>
    <main className="workspace"><header className="topbar"><div><p className="breadcrumb">POSTE DE CONTRÔLE / {NAVIGATION.find(item => item[0] === tab)?.[1].toUpperCase()}</p><h1>{tab === 'overview' ? 'Bonjour, Administrateur.' : NAVIGATION.find(item => item[0] === tab)?.[1]}</h1></div><div className="topbar-actions"><span className="live-pill"><i /> EN DIRECT</span><span className="date">{now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}<b>{now.toLocaleTimeString('fr-FR')}</b></span><button className="icon-button" aria-label="Notifications">♧<em>{stats.total_alerts || ''}</em></button></div></header>
      {tab === 'overview' && <Overview stats={stats} risk={risk} devices={devices} health={health} drone={drone} events={activeEvents} incidents={incidents} onDevice={openHistory} onAttack={launch} onMission={() => launch('/force_mission/entrepot_E01')} />}
      {tab === 'devices' && <Devices deviceList={deviceList} devices={devices} health={health} onDevice={openHistory} />}
      {tab === 'security' && <Security stats={stats} risk={risk} events={activeEvents} onAttack={launch} />}
      {tab === 'missions' && <Missions missions={missions} drone={drone} onMission={() => launch('/force_mission/entrepot_E01')} />}
      {tab === 'incidents' && <Incidents incidents={incidents} />}
      {tab === 'timeline' && <Timeline timeline={timeline} />}
      {tab === 'datalake' && <DataLake lake={lake} />}
      {tab === 'reports' && <Reports onReport={() => selectedDevice ? report(selectedDevice) : openHistory('entrepot_E01')} />}
    </main>
    {selectedDevice && <History device={selectedDevice} history={history} close={() => setSelectedDevice(null)} report={report} />}
  </div>;
}

function Overview({ stats, risk, devices, health, drone, events, incidents, onDevice, onAttack, onMission }) {
  const robot = drone; // CSS class names remain legacy; displayed terminology is drone.
  const cards = [['Équipements connectés', stats.active_devices, `${stats.total_devices} enregistrés`, 'teal'], ['Alertes actives', stats.total_alerts, 'À traiter', 'amber'], ['Menaces détectées', stats.attacks, 'Dernières 24 heures', 'red'], ['Niveau de risque', `${Number(risk.risk_score||0).toFixed(0)}%`, risk.level === 'High' ? 'Élevé' : risk.level === 'Medium' ? 'Modéré' : 'Faible', 'purple']];
  return <><section className="stat-grid">{cards.map(([title, value, foot, tone]) => <article className={`metric ${tone}`} key={title}><span>{title}</span><strong>{typeof value === "number" ? number(value) : value}</strong><small><i /> {foot}</small></article>)}</section><section className="overview-grid"><article className="panel map-panel"><div className="panel-heading"><div><p className="eyebrow">VUE OPÉRATIONNELLE</p><h2>Terminal Tanger Med</h2></div><button className="text-button">Vue satellite ↗</button></div><div className="terminal-map" style={{position:'relative',overflow:'hidden',backgroundImage:"url('/port.jpeg')",backgroundSize:'cover',backgroundPosition:'center 40%',height:380,borderRadius:9}}>
  <div style={{position:'absolute',inset:0,background:'linear-gradient(160deg,rgba(10,30,40,0.5) 0%,rgba(10,40,55,0.25) 100%)',zIndex:1}}/>
  <div style={{position:'absolute',top:14,left:16,zIndex:3,background:'rgba(255,255,255,0.15)',backdropFilter:'blur(8px)',borderRadius:8,padding:'6px 12px',border:'1px solid rgba(255,255,255,0.25)'}}>
    <span style={{fontSize:8,fontFamily:'DM Mono',letterSpacing:2,color:'#a0f0e8',textTransform:'uppercase'}}>📡 Vue Satellite · Tanger Med</span>
  </div>
  {Object.keys(DEVICE_LABELS).map(id => { const [left, top] = MAP_POSITIONS[id]; const data = devices[id] || {}; return <button key={id} className={`map-node ${statusOf(data.status)}`} style={{left:`${left}%`,top:`${top}%`,zIndex:2}} onClick={() => onDevice(id)}><b>{DEVICE_TYPES[id]}</b><span>{DEVICE_LABELS[id]}</span><i /></button>; })}
  <div className={`robot-pin ${robot.status !== 'idle' ? 'moving' : ''}`} style={{left:`${robot.x || 10}%`,top:`${robot.y || 10}%`,zIndex:3}}>✦<span>DRONE-01</span></div>
  <div className="map-key" style={{zIndex:3}}><span><i className="dot healthy"/> Opérationnel</span><span><i className="dot warning"/> Attention</span><span><i className="dot critical"/> Alerte</span></div>
</div></article><article className="panel event-panel"><div className="panel-heading"><div><p className="eyebrow">FLUX EN DIRECT</p><h2>Derniers événements</h2></div><span className="count-chip">{events.length}</span></div><div className="event-list">{events.length ? events.map((event, index) => <div className="event" key={index}><span className={`event-icon ${statusOf(event.status)}`}>{event.status === 'red' ? '!' : '◌'}</span><p><b>{DEVICE_LABELS[event.device_id] || event.device_id || 'Événement système'}</b><span>{event.last_value ?? event.value ?? 'Nouvelle activité détectée'}</span></p><time>{event.time}</time></div>) : <p className="empty">En attente d’activité…</p>}</div><button className="panel-link">Voir tout le journal →</button></article></section><section className="bottom-grid"><article className="panel fleet-panel"><div className="panel-heading"><div><p className="eyebrow">INSPECTION AUTONOME</p><h2>Drone d’inspection</h2></div><span className={`status-chip ${robot.status === 'idle' ? 'healthy' : 'warning'}`}>{robot.status === 'idle' ? 'Disponible' : 'En mission'}</span></div><div className="robot-content"><div className="robot-avatar">✦</div><div><b>DRONE-01</b><p>{robot.mission_id ? `Mission ${robot.mission_id}` : 'Aucune mission assignée'}</p><div className="battery"><span style={{ width: `${robot.battery || 0}%` }} /></div><small>Batterie {robot.battery ?? '--'}% · {robot.speed ? `${robot.speed.toFixed(1)} m/s` : 'Stationné'}</small></div><button className="secondary-button" onClick={onMission}>Déployer</button></div></article><article className="panel action-panel"><div><p className="eyebrow">SIMULATION</p><h2>Tester la résilience</h2><p>Déclenchez des scénarios contrôlés pour valider la détection.</p></div><div className="quick-actions"><button onClick={() => onAttack('/simulate/flood')}>≈<span>Flood MQTT</span></button><button onClick={() => onAttack('/simulate/spoof')}>◒<span>Spoofing</span></button><button onClick={() => onAttack('/simulate/unknown')}>?<span>Intrusion</span></button></div></article></section></>;
}

function Devices({ deviceList, devices, health, onDevice }) { const list = deviceList.length ? deviceList : Object.keys(DEVICE_LABELS).map(device_id => ({ device_id })); return <section className="panel table-panel"><div className="panel-heading"><div><p className="eyebrow">INVENTAIRE IOT</p><h2>Équipements du terminal</h2></div><span className="count-chip">{list.length} actifs</span></div><div className="device-table"><div className="table-head"><span>Équipement</span><span>Zone</span><span>Dernière mesure</span><span>Santé</span><span>État</span></div>{list.map(device => { const live = devices[device.device_id] || {}; const condition = live.status || (device.online === false ? 'red' : 'green'); return <button className="table-row" key={device.device_id} onClick={() => onDevice(device.device_id)}><span className="equipment"><b>{DEVICE_TYPES[device.device_id] || 'IO'}</b>{DEVICE_LABELS[device.device_id] || device.device_id}</span><span>{device.zone || 'Terminal principal'}</span><span>{live.last_value ?? device.last_value ?? '—'}</span><span><i className="health-bar"><b style={{ width: `${health[device.device_id] ?? device.health_score ?? 100}%` }} /></i>{health[device.device_id] ?? device.health_score ?? 100}%</span><span className={`status-chip ${statusOf(condition)}`}>{labelStatus(condition)}</span></button>; })}</div></section>; }

function Security({ stats, risk, events, onAttack }) { return <><section className="stat-grid security-metrics"><article className="metric red"><span>Incidents détectés</span><strong>{stats.attacks}</strong><small>Surveillance permanente</small></article><article className="metric amber"><span>Alertes ouvertes</span><strong>{stats.total_alerts}</strong><small>À qualifier</small></article><article className="metric purple"><span>Indice de risque</span><strong>{Number(risk.risk_score ?? 0).toFixed(0)}%</strong><small>Niveau {risk.level}</small></article></section><section className="two-column"><article className="panel"><div className="panel-heading"><div><p className="eyebrow">DÉTECTION</p><h2>Journal de sécurité</h2></div></div><div className="event-list">{events.map((event, index) => <div className="event" key={index}><span className={`event-icon ${statusOf(event.status)}`}>!</span><p><b>{event.device_id || 'Système'}</b><span>{event.last_value ?? event.value ?? 'Événement observé'}</span></p><time>{event.time}</time></div>)}</div></article><article className="panel scenario-panel"><p className="eyebrow">LABORATOIRE</p><h2>Scénarios de sécurité</h2><p>Ces actions simulent des attaques sur l’environnement de démonstration.</p><button className="danger-button" onClick={() => onAttack('/simulate/flood')}>Lancer un flood MQTT <span>→</span></button><button className="outline-button" onClick={() => onAttack('/simulate/spoof')}>Simuler une usurpation</button><button className="outline-button" onClick={() => onAttack('/simulate/impossible')}>Injecter une valeur anormale</button></article></section></>; }

function Missions({ missions, drone, onMission }) { return <section className="two-column"><article className="panel"><div className="panel-heading"><div><p className="eyebrow">DRONE-01</p><h2>État de la flotte</h2></div><span className="status-chip healthy">En ligne</span></div><div className="mission-hero"><div className="robot-avatar large">✦</div><div><strong>{drone.status === 'idle' ? 'Prêt à intervenir' : 'Intervention en cours'}</strong><p>{drone.mission_id || 'Le drone attend sa prochaine mission.'}</p><div className="battery"><span style={{ width: `${drone.battery || 0}%` }} /></div><small>Batterie : {drone.battery ?? '--'}% · Position : {Number(drone.x || 0).toFixed(0)}, {Number(drone.y || 0).toFixed(0)}</small></div></div><button className="primary-button compact" onClick={onMission}>Créer une mission d’inspection <span>→</span></button></article><article className="panel"><p className="eyebrow">HISTORIQUE</p><h2>Missions récentes</h2><div className="event-list">{missions.length ? missions.map((mission, index) => <div className="event" key={index}><span className="event-icon healthy">◎</span><p><b>{mission.mission_id || 'Mission autonome'}</b><span>{mission.device_id || 'Terminal'} · {mission.status || 'pending'}</span></p><time>{mission.created_at ? new Date(mission.created_at).toLocaleTimeString('fr-FR') : '—'}</time></div>) : <p className="empty">Aucune mission enregistrée.</p>}</div></article></section>; }

function Incidents({ incidents }) { return <section className="panel table-panel"><div className="panel-heading"><div><p className="eyebrow">GESTION DES ALERTES</p><h2>Incidents déclarés</h2></div></div><div className="device-table"><div className="table-head"><span>Référence</span><span>Équipement</span><span>Type</span><span>Gravité</span><span>État</span></div>{incidents.length ? incidents.map(item => <div className="table-row" key={item.id}><span>#INC-{item.id}</span><span>{DEVICE_LABELS[item.device_id] || item.device_id}</span><span>{item.anomaly_type || 'Anomalie'}</span><span className={`severity ${item.severity || 'medium'}`}>{item.severity || 'medium'}</span><span className="status-chip warning">{item.status || 'open'}</span></div>) : <p className="empty">Aucun incident déclaré.</p>}</div></section>; }

function Timeline({ timeline }) { return <section className="panel timeline-panel"><p className="eyebrow">CHRONOLOGIE</p><h2>Activité du terminal</h2><div className="timeline-list">{timeline.length ? timeline.map((item, index) => <div className="timeline-row" key={index}><time>{item.time ? new Date(item.time).toLocaleString('fr-FR') : 'À l’instant'}</time><i className={item.type || 'alert'} /><div><span>{item.type || 'événement'}</span><p>{item.message}</p></div></div>) : <p className="empty">Aucune activité récente.</p>}</div></section>; }

function DataLake({ lake }) { const streams = Object.entries(lake.streams || {}); return <section className="panel table-panel"><div className="panel-heading"><div><p className="eyebrow">DATA LAKE · JSONL</p><h2>Preuves opérationnelles append-only</h2></div><span className="status-chip healthy">{lake.retention || 'append-only'}</span></div><div className="device-table"><div className="table-head"><span>Flux</span><span>Format</span><span>Fichiers</span><span>Événements</span><span>Usage</span></div>{streams.map(([name, data]) => <div className="table-row" key={name}><span>{name}</span><span>{lake.format || 'jsonl'}</span><span>{data.files}</span><span>{number(data.events)}</span><span>Analyse / SIEM</span></div>)}{!streams.length && <p className="empty">En attente des données du Data Lake.</p>}</div></section>; }

function Reports({ onReport }) { return <section className="panel reports-panel"><div className="report-icon">▤</div><p className="eyebrow">CENTRE DOCUMENTAIRE</p><h2>Rapports d’incident</h2><p>Générez un rapport PDF depuis l’historique d’un équipement. Les documents sont stockés dans le dossier <code>reports/</code> du projet.</p><button className="primary-button compact" onClick={onReport}>Préparer un rapport <span>→</span></button></section>; }

function History({ device, history, close, report }) { return <div className="modal-backdrop" onMouseDown={close}><section className="history-modal" onMouseDown={event => event.stopPropagation()}><button className="close-button" onClick={close}>×</button><p className="eyebrow">TÉLÉMÉTRIE · {DEVICE_TYPES[device] || 'IO'}</p><h2>{DEVICE_LABELS[device] || device}</h2><p className="chart-subtitle">Dernières mesures reçues</p><div className="chart">{history.length ? <ResponsiveContainer><LineChart data={history}><CartesianGrid stroke="#e4edf1" vertical={false}/><XAxis dataKey="time" tickLine={false} axisLine={false}/><YAxis tickLine={false} axisLine={false}/><Tooltip/><Line type="monotone" dataKey="value" stroke="#0c9d91" strokeWidth={3} dot={false}/></LineChart></ResponsiveContainer> : <p className="empty">Aucune mesure disponible.</p>}</div><footer><button className="outline-button" onClick={close}>Fermer</button><button className="primary-button compact" onClick={() => report(device)}>Générer le PDF <span>→</span></button></footer></section></div>; }

export default App;
