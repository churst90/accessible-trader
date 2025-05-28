# views.py
import logging
from quart import Blueprint, render_template, session as quart_session # Using quart_session for example
# from middleware.auth_middleware import jwt_required # You might protect some views later

logger = logging.getLogger(__name__)

# Create a blueprint for frontend views
frontend_bp = Blueprint(
    "frontend",
    __name__,
    template_folder="templates" # Tells Quart where to find this blueprint's templates
)

# Basic route for the home page
@frontend_bp.route("/")
async def serve_home_page():
    """Serves the main home page (index.html)."""
    logger.debug("Serving home page from frontend_bp.")
    # For initial page load, auth status is tricky with JWTs.
    # Client-side JS will usually handle UI changes post-load based on JWT in localStorage.
    # Passing a server-side session flag is an option if you set one during API login.
    user_is_authenticated = quart_session.get("user_id") is not None # Example placeholder
    return await render_template("index.html", user_is_authenticated=user_is_authenticated)

# Route for the chart page
@frontend_bp.route("/chart")
async def serve_chart_page():
    """Serves the main chart page (chart.html)."""
    logger.debug("Serving chart page from frontend_bp.")
    user_is_authenticated = quart_session.get("user_id") is not None # Example placeholder
    return await render_template("chart.html", user_is_authenticated=user_is_authenticated)

@frontend_bp.route("/faq")
async def serve_faq_page():
    logger.debug("Serving FAQ page from frontend_bp.")
    user_is_authenticated = quart_session.get("user_id") is not None # Example placeholder
    return await render_template("faq.html", user_is_authenticated=user_is_authenticated)

@frontend_bp.route("/support")
async def serve_support_page():
    logger.debug("Serving Support page from frontend_bp.")
    user_is_authenticated = quart_session.get("user_id") is not None # Example placeholder
    return await render_template("support.html", user_is_authenticated=user_is_authenticated)

# Routes for login and registration page shells
@frontend_bp.route("/login")
async def serve_login_page():
    logger.debug("Serving Login page shell from frontend_bp.")
    return await render_template("login.html")

@frontend_bp.route("/register")
async def serve_register_page():
    logger.debug("Serving Register page shell from frontend_bp.")
    return await render_template("register.html")

# You can add more routes here for other pages like /profile, /credentials, /bots
# For example:
# @frontend_bp.route("/profile")
# # @jwt_required # You'd need to adapt jwt_required or have client-side routing handle this
# async def serve_profile_page():
#     logger.debug("Serving Profile page shell from frontend_bp.")
#     # Ensure user is authenticated before rendering a page that requires it.
#     # Client-side will also verify with JWT for API calls.
#     return await render_template("profile.html")