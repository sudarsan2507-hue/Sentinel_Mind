import { useEffect, useRef, useState, useCallback } from 'react';
import { io } from 'socket.io-client';

/**
 * useSocket – manages a single Socket.IO connection to the Flask backend.
 *
 * The socket connects to the same origin in dev (Vite proxies /socket.io to port 5000).
 * In production Flask serves the built React app so same-origin applies automatically.
 */
export function useSocket() {
  const socketRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);

  const emit = useCallback((event, data) => {
    socketRef.current?.emit(event, data);
  }, []);

  const on = useCallback((event, handler) => {
    socketRef.current?.on(event, handler);
    return () => socketRef.current?.off(event, handler);
  }, []);

  useEffect(() => {
    const socket = io({ path: '/socket.io', transports: ['websocket', 'polling'] });
    socketRef.current = socket;

    socket.on('connect', () => setConnected(true));
    socket.on('disconnect', () => setConnected(false));
    socket.on('connect_error', () => setConnected(false));

    // Expose raw last-event for convenience
    const eventNames = ['verdict', 'trace', 'goal', 'cleared', 'learned', 'server_error', 'summary'];
    eventNames.forEach((name) => {
      socket.on(name, (data) => setLastEvent({ type: name, data, ts: Date.now() }));
    });

    return () => {
      socket.disconnect();
    };
  }, []);

  return { connected, lastEvent, on, emit };
}
