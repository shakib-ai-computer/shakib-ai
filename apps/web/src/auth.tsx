import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { getMe, getToken, setToken, type MeResponse } from './api'

interface AuthState {
  user: MeResponse | null
  /** True while a stored token is being validated against /api/auth/me. */
  loading: boolean
  signIn: (token: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: false,
  signIn: async () => {},
  signOut: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(() => getToken() !== null)

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      setUser(await getMe())
    } catch {
      // Stored token is invalid/expired (or the backend is down): drop it
      // so the UI falls back to guest mode instead of erroring everywhere.
      setToken(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const signIn = useCallback(
    async (token: string) => {
      setToken(token)
      await refresh()
    },
    [refresh],
  )

  const signOut = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, signIn, signOut }),
    [user, loading, signIn, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  return useContext(AuthContext)
}
