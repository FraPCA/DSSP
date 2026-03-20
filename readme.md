# DSSP
<p align = "center">
  <p>
  An implementation of the Distributed Secret Sharing Protocol, as outlined in the paper written by Alfredo De Santis and Barbara Masucci, originally presented at DBSEC 2023.
  <br>
  <br>
  Written by Francesco Maria Puca as part of a Master's Thesis in Informatica (Computer Science), specialization in Software Engineering and IT Management, at Università degli Studi di Salerno.
  <br>
  <br>
  Thesis project conducted under the supervision of Barbara Masucci.
</p>

# Dependencies
This implementation is written as a Python program, and therefore requires the installation of Python 3.13.2 or later.

# Install instructions
<p>
 To run this project, it is recommended to create a virtual environment (venv) in the folder in which the program will be executed.
 To do so, run the command: <h2> python3 -m venv foldername </h2> , then extract the downloaded project in the same folder.
 Afterwards, execute your shell program, and use the command: <h2>foldername\Scripts\Activate.ps1</h2> on Windows, or source foldername/bin/activate on Linux.
 In the same terminal window, the command: pip install -r requirements.txt must be executed to download and install the project's dependencies in the virtual environment.
Once these operations have been completed, the project can be executed by activating the virtual environment, and afterwards executing the command python3 dssp.py .
</p>

# Benchmarking
<p>
  To execute this project's associated local benchmarks, run the command pytest dssp.py in an activated terminal window.
</p>
