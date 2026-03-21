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
 To do so, run the command: <em><strong> python3 -m venv foldername </strong></em> , then extract the downloaded project in the same folder.
 Afterwards, execute your shell program, and use the command:  <em><strong>foldername\Scripts\Activate.ps1</strong></em> on Windows, or <em><strong>source foldername/bin/activate </strong></em> on Linux.
 In the same terminal window, the command: <em><strong>pip install -r requirements.txt </strong></em> must be executed to download and install the project's dependencies in the virtual environment.
Once these operations have been completed, the project can be executed by activating the virtual environment, and afterwards executing the command: <em><strong>python3 dssp.py </strong></em>.
</p>

# Benchmarking
<p>
  To execute this project's associated local benchmarks, run the command: <em><strong>pytest dssp.py </strong></em>in an activated terminal window.
</p>
