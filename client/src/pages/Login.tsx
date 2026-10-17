import { FormEvent, useState} from "react";
import { useNavigate } from "react-router-dom";
import {useAuth} from "../auth/AuthContext";
// CSS imports are resolved by the bundler; moduleResolution is "bundler".
import "../shell.css";

export function LoginPage() {
    const navigate = useNavigate();

    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const {loginUser} = useAuth();

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        
        setError("");
        setLoading(true);

        try{
            await loginUser(username,password);
            navigate("/");
        } catch (err) {
            setError(
                err instanceof Error ? err.message : "Unable to log in"
            );
        } finally {
            setLoading(false);
        }

    }

    return(
        <div className="login-page">
            <div className="login-panel">
                <div className="login-heading">
                    <b>TDAC</b>
                    <h1>Sign In</h1>
                    <p>Sign in to access the TDAC system.</p>
                </div>

                <form onSubmit={handleSubmit}>
                    <label htmlFor="username">Username</label>
                    <input 
                        type="text"
                        id="username"
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        autoComplete="username"
                        required
                     />

                     <label htmlFor="password">Password</label>
                     <input 
                        type="password" 
                        id ="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        autoComplete="current-password"
                        required
                     />
                     
                     {error && <div className ="login-error">{error}</div>}
                     <button type ="submit" disabled={loading}>
                        {loading ? "Signing in...": "Sign in"}
                     </button>
                </form>
            </div>
        </div>
    );
}