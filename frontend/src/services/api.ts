import axios, { type AxiosRequestConfig } from "axios";

const client = axios.create({ baseURL: "/api", timeout: 30000 });

client.interceptors.request.use((config) => {
  const stored = localStorage.getItem("campus-qa-auth");
  if (stored) {
    const { token } = JSON.parse(stored);
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (res) => res.data?.data ?? res.data,
  (err) => {
    const isAuthRequest = err.config?.url?.startsWith("/auth/");
    if (err.response?.status === 401 && !isAuthRequest) {
      localStorage.removeItem("campus-qa-auth");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

interface ApiClient {
  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>;
  post<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>;
  put<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>;
  patch<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>;
  delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>;
}

export default client as unknown as ApiClient;
