import { useState, type FormEvent } from "react";
import { useNavigate } from 'react-router';

function Login() {
    const [username,setUsername] =  useState('');
    const [password, setPassword] =  useState('');
    const [error, setError] =  useState('');
    const [loading, setLoading] =  useState(false);
    const navigate = useNavigate();
    const validateForm = () => {
        if (!username || !password) {
            setError('Username and password are required');
            return false;
        }
        setError('');
        return true;
    };
    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!validateForm()) return;
        setLoading(true);

        const formDetails = new URLSearchParams();
        formDetails.append('username', username)
        formDetails.append('password', password)

        try {
            const response = await fetch(`${import.meta.env.VITE_AUTH_URL}/token`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: formDetails
            });

        setLoading(false);

        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('token', data.access_token);
            navigate('/protected');
        } else {
            const errorData = await response.json();
            setError(errorData.detail || 'Authentification failed');
        }
        } catch {
            setLoading(false);
            setError('An error occured. Please try again later.');
        }
    };

    return (
        <div>
            <form onSubmit={handleSubmit}>
                <div>
                    <label>Username:</label>
                    <input
                        type="text"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                    />
                </div>
                <div>
                    <label>Password:</label>
                    <input
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                    />
                </div>
                <button type="submit" disabled={loading}>
                    {loading ? 'Logging in...': 'Login'}
                </button>
                {error && <p style={{color: 'red'}}>{error}</p>}
            </form>
        </div>
    );
}

export default Login;
