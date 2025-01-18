# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import genvarloader

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "GenVarLoader"
copyright = "2024, David Laub"
author = "David Laub"
release = genvarloader.__version__
# short X.Y verison
version = ".".join(release.split(".")[:2])

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration
templates_path = ["_templates"]
exclude_patterns = []

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.mathjax",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "myst_parser",
    "nbsphinx",
]

autodoc_typehints = "description"
autodoc_class_signature = "separated"
autodoc_typehints_format = "short"
autodoc_default_options = {"private-members": False}
autodoc_member_order = "bysource"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "numba": ("https://numba.readthedocs.io/en/stable/", None),
    "torch": ("https://pytorch.org/docs/stable/", None),
}

napoleon_google_docstring = False
napoleon_use_param = True
napoleon_type_aliases = {
    "Path": ":class:`Path <pathlib.Path>`",
    "Callable": ":class:`Callable <typing.Callable>`",
    "ArrayLike": ":external+numpy:term:`ArrayLike <array_like>`",
    "NDArray": ":external+numpy:class:`NDArray <numpy.typing.NDArray>`",
    "DataFrame": "pl.DataFrame",
}
napoleon_preprocess_types = True
napoleon_use_rtype = True

always_use_bar_unions = True
simplify_optional_unions = True
typehints_defaults = "comma"

myst_enable_extensions = ["colon_fence", "deflist", "dollarmath", "amsmath"]

nbsphinx_execute = "auto"
nbsphinx_kernel_name = "python3"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_book_theme"
html_static_path = ["_static"]
html_theme_options = {
    "home_page_in_toc": True,
    "repository_url": "https://github.com/mcvickerlab/GenVarLoader",
    "use_repository_button": True,
    "pygments_light_style": "tango",
    "pygments_dark_style": "material",
    "show_toc_level": 2,
}
highlight_language = "python"
html_logo = "_static/gvl_logo.png"
html_favicon = "_static/favicon.ico"
html_title = f"GenVarLoader v{version}"
html_sidebars = {
    "**": [
        "navbar-logo.html",
        "icon-links.html",
        "search-button-field.html",
        "sbt-sidebar-nav.html",
    ]
}
