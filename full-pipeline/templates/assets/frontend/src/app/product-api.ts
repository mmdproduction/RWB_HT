/** Same-origin API transport for the generated product. Public tools renew their demo token once on 401. */
let publicRole: string | null = null;
let renewal: Promise<string> | null = null;

export function configureProductApi(role: string, publicAccess: boolean): void {
  publicRole = publicAccess ? role : null;
}

async function renewPublicToken(): Promise<string> {
  if (!renewal) {
    renewal = (async () => {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({role: publicRole}), redirect: 'error'
      });
      if (!response.ok) throw new Error('Не удалось восстановить подключение. Повторите попытку.');
      const data = await response.json();
      if (typeof data.token !== 'string' || !data.token) throw new Error('Сервис не вернул данные подключения.');
      sessionStorage.setItem('demo-token', data.token);
      sessionStorage.setItem('demo-role', data.role);
      return data.token;
    })().finally(() => { renewal = null; });
  }
  return renewal;
}

export async function productFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (!path.startsWith('/api/')) throw new Error('Ожидается внутренний адрес API приложения.');
  const send = () => {
    const headers = new Headers(init.headers);
    const token = sessionStorage.getItem('demo-token');
    if (token) headers.set('Authorization', 'Bearer ' + token);
    return fetch(path, {...init, headers, redirect: 'error'});
  };
  let response = await send();
  if (response.status === 401 && publicRole && path !== '/api/auth/login') {
    await renewPublicToken();
    response = await send();
  }
  return response;
}
