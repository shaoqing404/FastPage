import axios from 'axios';

const BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '') || '/';
const browserOriginApiBase =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:22223/api/v1`
    : 'http://localhost:22223/api/v1';
const inferredApiBase =
  BASENAME === '/'
    ? browserOriginApiBase
    : `${BASENAME.replace(/\/web$/, '')}/api/v1`;
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || inferredApiBase;

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      const loginPath = `${BASENAME === '/' ? '' : BASENAME}/login`;
      if (window.location.pathname !== loginPath) {
        window.location.href = loginPath;
      }
    }
    return Promise.reject(error);
  }
);
