# modules/auth.py
import streamlit as st
import modules.utils as utils # Importamos las herramientas que acabamos de crear

def check_password():
    """Retorna True si el usuario está logueado, False si no."""
    
    if st.session_state.get("password_correct", False):
        return True

    # Diseño del Login
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("###")
        st.image("GravityStats_Logo.png", width=200)
        st.markdown("### 🔒 Iniciar Sesión")

        with st.form("login_form"):
            email = st.text_input("Usuario / Correo")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Entrar", use_container_width=True)

        if submit:
            # Validar contra secrets.toml
            if email in st.secrets["passwords"] and st.secrets["passwords"][email] == password:
                st.session_state["password_correct"] = True
                st.session_state["user_email"] = email
                
                # TRACKING: Registrar Login Exitoso
                with st.spinner("Accediendo..."):
                    utils.registrar_evento(email, "Login Exitoso")
                
                st.rerun()
            else:
                st.error("😕 Usuario o contraseña incorrectos")
                
    return False