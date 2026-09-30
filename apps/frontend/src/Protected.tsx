import { useEffect } from "react";
import { useNavigate } from "react-router";

function ProtectedPage() {
    const navigate = useNavigate();

    useEffect(() => {
        const verifyToken = async () => {
            const token = localStorage.getItem('token');
                console.log(token)
            try {
                const response = await fetch(`${import.meta.env.VITE_AUTH_URL}/verify-token/${token}`);

                if (!response.ok) {
                    throw new Error('Token verification failed');
                }
            } catch {
                localStorage.removeItem('token');
                navigate('/');
            }
        };

        verifyToken();
    }, [navigate]);

    return <div>This is a protected page. Only visible to authentificated users.</div>
}

export default ProtectedPage;
