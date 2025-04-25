# Use a base image with Python 3.11.8
FROM python:3.11.8

# Install updated pip, setuptools, and wheel
RUN pip install --upgrade pip setuptools wheel

# Install crewai and its tools
RUN pip install poetry

# Clone crewai-sheet-ui
RUN git clone https://github.com/yuriwa/crewai-sheets-ui.git /home/user/root/crewai-sheets-ui 
# Set the working directory in the Docker image
WORKDIR /home/user/root/crewai-sheets-ui

ENV PEP517_BUILD_BACKEND=setuptools.build_meta

# Configure poetry to not create a virtual environment and install dependencies
RUN poetry config virtualenvs.create false && poetry install

RUN pip install langchain_groq
RUN pip install sentry-sdk

RUN mkdir /home/user/root/ENV
# Create an .env file and add the exports
RUN echo "export VAR1=value1\nexport VAR2=value2\nexport VAR3=value3\nexport VAR4=value4\nexport VAR5=value5\nexport VAR6=value6\nexport VAR7=value7\nexport VAR8=value8\nexport VAR9=value9" > /home/user/root/crewai-sheets-ui/../ENV/.env

# Expose port 11434
#EXPOSE 11434

WORKDIR /home/user/root/savefiles

CMD if [ -z "$OPENAI_API_KEY" ]; then \
      echo "See https://github.com/yuriwa/crewai-sheets-ui for instructions on how run this Docker container" && \
      echo "Minimal usage: docker run -it -p 11434:11434 -v $(pwd)/savefiles:/home/user/root/savefiles -e OPENAI_API_KEY='YOUR API KEY' crewai-image" && \
      echo "You can replace $(pwd)$(pwd)/savefiles with the path to your savefiles folder"; \
    elif [ ! -d "/home/user/root/savefiles" ]; then \
      echo "The required volume is not mounted." && \
      echo "See https://github.com/yuriwa/crewai-sheets-ui for instructions on how run this Docker container" && \
      echo "Minimal usage: docker run -it -p 11434:11434 -v $(pwd)/savefiles:/home/user/root/savefiles -e OPENAI_API_KEY='YOUR API KEY' crewai-image" && \
      echo "You can replace $(pwd)$(pwd)/savefiles with the path to your savefiles folder"; \
    fi



